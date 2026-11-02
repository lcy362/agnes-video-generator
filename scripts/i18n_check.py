#!/usr/bin/env python3
"""多语言完整性检查脚本（优化路线图 1.8 硬化版）。

检查 frontend/src/i18n/langs/*.json（22 个语言 JSON）相对 zh（基准语言）的一致性：
1. key 缺失：任何语言相对 zh 的缺失
   - en 缺失 → 硬阻断（返回码 2，CI / 回归前置门槛）
   - 其余语言缺失 → 列出提醒（返回码 1；回归脚本同样视为不通过）
2. 占位符不一致：值中 ``{xxx}`` 占位符集合与 zh 不一致 → 提醒（不阻断）
3. 可疑未翻译：en 值与 zh 完全相同（非纯占位/短文案）→ 提醒（不阻断）
4. 中文泄漏：非中文语言的值里残留汉字（整段照抄 zh，用户界面直接看到中文）
   → 提醒（不阻断）。``ja`` 因正文本就含汉字（Kanji）不参与该项检测。

用法:
    python scripts/i18n_check.py          # 全量检查（退出码 0/1/2）
    python scripts/i18n_check.py --json   # 输出 JSON（问题映射）
"""

import argparse
import json
import re
import sys
from pathlib import Path

# 基准语言：所有其他语言的 key 集合必须覆盖 zh 的 key 集合
BASE_LANG = 'zh'
# 硬阻断语言：缺失直接返回 2（CI 硬失败 / 回归前置门槛）
HARD_LANG = 'en'
# 中文泄漏检测跳过 jap：日文正文本就含汉字（Kanji），按码位判断全是误报
CJK_LEAK_SKIP = {'zh', 'ja'}
#: 汉字码位区间（CJK 统一表意文字，含扩展 A 的首段）
CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def load_langs(langs_dir: Path) -> dict[str, dict[str, str]]:
    """加载 langs/*.json → {lang: {key: value}}。"""
    result: dict[str, dict[str, str]] = {}
    for p in sorted(langs_dir.glob('*.json')):
        result[p.stem] = json.loads(p.read_text(encoding='utf-8'))
    return result


def placeholder_set(text: str) -> set[str]:
    """提取文本中的 ``{xxx}`` 占位符集合。"""
    return set(re.findall(r'\{(\w+)\}', text or ''))


def find_cjk_leak(langs_dir: Path) -> dict[str, list[str]]:
    """返回 ``{lang: [key]}``：该语言的值里残留汉字（整段照抄 zh）。

    判定口径：值的汉字命中 ≥1 个，且该 key 的 zh 值本身就含汉字（说明是照抄），
    同时排除 :data:`CJK_LEAK_SKIP`（zh 是源语言、ja 的汉字属正常）。纯属提醒，
    不影响退出码——典型场景是新增文案只补了 zh/en，其余语言直接复制中文占位。
    """
    langs = load_langs(langs_dir)
    base = langs.get(BASE_LANG, {})
    leak: dict[str, list[str]] = {}
    for lang, d in langs.items():
        if lang in CJK_LEAK_SKIP:
            continue
        hits = [
            k for k, v in d.items()
            if isinstance(v, str) and CJK_RE.search(v)
            and CJK_RE.search(base.get(k, '') or '')
        ]
        if hits:
            leak[lang] = sorted(hits)
    return leak


def check(langs_dir: Path) -> tuple[dict, dict, dict]:
    """返回 (missing, placeholder_mismatch, suspicious_same_as_zh)。"""
    langs = load_langs(langs_dir)
    base = langs[BASE_LANG]
    if base is None:
        raise ValueError(f'缺少基准语言 {BASE_LANG}')

    missing: dict[str, list[str]] = {}
    placeholder_mismatch: dict[str, dict] = {}
    suspicious_same_as_zh: list[str] = []

    for lang, d in langs.items():
        if lang == BASE_LANG:
            continue
        # 1) key 缺失
        diff = set(base) - set(d)
        if diff:
            missing[lang] = sorted(diff)
        # 2) 占位符一致性：zh 值含 {xxx} 的 key，该语言值应含相同占位符集合
        ph_mm: dict[str, dict] = {}
        for k, zh_v in base.items():
            zh_ph = placeholder_set(zh_v)
            if not zh_ph:
                continue
            other_ph = placeholder_set(d.get(k, ''))
            if other_ph != zh_ph:
                ph_mm[k] = {'zh': sorted(zh_ph), lang: sorted(other_ph)}
        if ph_mm:
            placeholder_mismatch[lang] = ph_mm
        # 3) 可疑未翻译（仅 en）：与 zh 完全相同且非纯占位/短文案
        if lang == HARD_LANG:
            suspicious_same_as_zh = [
                k for k in base
                if d.get(k) == base[k]
                and len(base[k]) > 4
                and not placeholder_set(base[k])
            ]
    return missing, placeholder_mismatch, suspicious_same_as_zh


def main() -> int:
    parser = argparse.ArgumentParser(description='多语言完整性检查（JSON 硬化版）')
    parser.add_argument('--path', default='frontend/src/i18n/langs',
                        help='langs 目录路径（相对项目根目录）')
    parser.add_argument('--json', action='store_true', help='输出 JSON 格式')
    args = parser.parse_args()

    langs_dir = Path(args.path)
    if not langs_dir.is_dir():
        print(f'[i18n_check] 目录不存在: {langs_dir}', file=sys.stderr)
        return 2

    try:
        missing, ph_mismatch, suspicious = check(langs_dir)
        cjk_leak = find_cjk_leak(langs_dir)
    except (ValueError, json.JSONDecodeError, OSError) as e:
        print(f'[i18n_check] 解析失败: {e}', file=sys.stderr)
        return 2

    en_missing = missing.get(HARD_LANG, [])
    other_missing = {lang: m for lang, m in missing.items() if lang != HARD_LANG}

    if args.json:
        print(json.dumps({
            'missing': missing,
            'placeholder_mismatch': ph_mismatch,
            'suspicious_same_as_zh': suspicious,
            'cjk_leak': cjk_leak,
        }, ensure_ascii=False, indent=2))
        return 2 if en_missing else (1 if other_missing else 0)

    hard_fail = False
    if en_missing:
        hard_fail = True
        print(f'[i18n_check] ❌ en 缺失 {len(en_missing)} 个 key（硬阻断）：'
              f'{en_missing[:8]}{"..." if len(en_missing) > 8 else ""}')
    if other_missing:
        print('[i18n_check] ⚠ 其他语言缺失，需补齐后再回归：')
        for lang, keys in sorted(other_missing.items()):
            print(f'  {lang}: 缺失 {len(keys)} 个 key → {keys[:8]}{"..." if len(keys) > 8 else ""}')
    if ph_mismatch:
        print('[i18n_check] ⚠ 占位符不一致（zh 为基准，不阻断）：')
        for lang, km in sorted(ph_mismatch.items()):
            for k, ph in km.items():
                print(f'  {lang}.{k}: zh={ph["zh"]} vs {ph[lang]}')
    if suspicious:
        print(f'[i18n_check] ⚠ 可疑未翻译（en 与 zh 完全相同，仅提醒）：'
              f'{suspicious[:8]}{"..." if len(suspicious) > 8 else ""}')
    if cjk_leak:
        total = sum(len(v) for v in cjk_leak.values())
        union = sorted({k for v in cjk_leak.values() for k in v})
        print(f'[i18n_check] ⚠ 中文泄漏（值仍是中文占位，{len(cjk_leak)} 种语言 / '
              f'{len(union)} 个 key，共 {total} 处，仅提醒）：')
        for lang, keys in sorted(cjk_leak.items()):
            print(f'  {lang}: {len(keys)} 个 → {keys[:6]}{"..." if len(keys) > 6 else ""}')
    if not hard_fail and not other_missing:
        print('[i18n_check] ✅ 多语言完整，无缺失')
        return 0

    return 2 if hard_fail else 1


if __name__ == '__main__':
    sys.exit(main())
