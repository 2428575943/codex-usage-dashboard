"""Quota policy and reversible Codex configuration. No chat content or credentials."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import tomllib
import uuid

VERSION = '0.1.0'
EFFORTS = ('low', 'medium', 'high')
LUNA = 'gpt-6-luna'
TERRA = 'gpt-6.1-terra'
SOL = 'gpt-6.1-sol'
FUTURE_SOL = 'gpt-6.2-sol'
MAX_QUOTA_AGE = 600


def atomic_bytes(path: Path, value: bytes):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with tmp.open('xb') as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_bytes(Path(path), json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return copy.deepcopy(default)


def policy(remaining):
    if remaining is None:
        return 'unknown', [LUNA]
    if isinstance(remaining, bool) or not isinstance(remaining, (float, int)) or not math.isfinite(remaining) or not 0 <= remaining <= 100:
        raise ValueError('invalid_remaining_percent')
    if remaining > 30:
        return 'full', [TERRA, SOL, LUNA, FUTURE_SOL]
    if remaining >= 15:
        return 'balanced', [TERRA, LUNA]
    return 'save', [LUNA]


def quota_from_result(result, account, now=None):
    """Only a 300 minute codex bucket is the requested 5h quota."""
    now = time.time() if now is None else now
    buckets = result.get('rateLimitsByLimitId') or {}
    if not buckets:
        entry = result.get('rateLimits') or {}
        if entry.get('limitId', 'codex') == 'codex':
            buckets = {'codex': entry}
    entry = buckets.get('codex') or {}
    for name in ('primary', 'secondary'):
        part = entry.get(name)
        if not isinstance(part, dict) or part.get('windowDurationMins') != 300:
            continue
        used, reset = part.get('usedPercent'), part.get('resetsAt')
        if type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used <= 100:
            continue
        if type(reset) not in (int, float) or not math.isfinite(reset) or reset <= now:
            continue
        return dict(remaining=100-used, resets_at=reset, observed_at=now,
                    account=account, source='codex_app_server', window_minutes=300)
    return None


def valid_quota(quota, account, now=None):
    now = time.time() if now is None else now
    if not isinstance(quota, dict) or not account or quota.get('account') != account:
        return None
    try:
        age = now - quota['observed_at']
        if not 0 <= age <= MAX_QUOTA_AGE or quota['resets_at'] <= now:
            return None
        policy(quota['remaining'])
        return quota['remaining']
    except (KeyError, TypeError, ValueError):
        return None


def filtered_catalog(source, remaining):
    tier, allowed = policy(remaining)
    models = []
    for raw in source.get('models', []):
        slug = raw.get('slug')
        # Preserve internal safety machinery. It is never shown in the model picker.
        if slug == 'codex-auto-review' and raw.get('visibility') == 'hide':
            models.append(copy.deepcopy(raw))
        elif slug in allowed:
            item = copy.deepcopy(raw)
            levels = [r for r in item.get('supported_reasoning_levels', []) if r.get('effort') in EFFORTS]
            if {r['effort'] for r in levels} != set(EFFORTS):
                raise ValueError('model_missing_requested_efforts:' + slug)
            item['supported_reasoning_levels'] = levels
            if item.get('default_reasoning_level') not in EFFORTS:
                item['default_reasoning_level'] = 'medium'
            item['visibility'] = 'list'
            # Do not advertise automatic upgrades to models excluded by this policy.
            item['upgrade'] = None
            models.append(item)
    visible = [m['slug'] for m in models if m.get('visibility') == 'list']
    if LUNA not in visible:
        raise ValueError('luna_not_in_current_catalog')
    return {'models': models}, tier, visible


def load_source(home: Path):
    paths = list(home.glob('models_cache*.json'))
    paths.sort(key=lambda p: (p.name == 'models_cache.codex_work_desktop.json', p.stat().st_mtime), reverse=True)
    for path in paths:
        source = read_json(path)
        if isinstance(source, dict) and source.get('models'):
            try:
                filtered_catalog(source, None)
                return source, path
            except ValueError:
                pass
    raise ValueError('no_compatible_official_model_cache')


def config_value(config, key):
    node = config
    for part in key.split('.'):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def edit_config(text, edits):
    """Edit only owned simple assignments. Validate before and after; retain other bytes."""
    original = tomllib.loads(text)
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = text.splitlines(keepends=True)
    for full, value in edits.items():
        section, _, key = full.rpartition('.')
        current, matches, section_end, section_found = '', [], len(lines), not section
        section_start = 0
        for i, line in enumerate(lines):
            header = re.match(r'^\s*\[([^\[\]]+)\]\s*(?:#.*)?$', line.strip())
            if header:
                if current == section:
                    section_end = i
                current = header.group(1).strip()
                if current == section:
                    section_found, section_start, section_end = True, i+1, len(lines)
            if current == section and re.match(r'^\s*' + re.escape(key) + r'\s*=', line):
                matches.append(i)
        if len(matches) > 1:
            raise ValueError('ambiguous_config_key:' + full)
        if matches:
            i = matches[0]
            # Only replace a complete, independently parseable single line.
            try:
                tomllib.loads(lines[i])
            except tomllib.TOMLDecodeError as e:
                raise ValueError('complex_config_assignment:' + full) from e
            if value is None:
                del lines[i]
            else:
                lines[i] = key + ' = ' + json.dumps(value, ensure_ascii=False) + newline
        elif value is not None:
            if config_value(original, full) is not None:
                raise ValueError('unsupported_config_spelling:' + full)
            assignment = key + ' = ' + json.dumps(value, ensure_ascii=False) + newline
            if section_found:
                if section_end and not lines[section_end-1].endswith(('\n', '\r')):
                    lines[section_end-1] += newline
                lines.insert(section_end, assignment)
            else:
                lines.extend([newline + '[' + section + ']' + newline, assignment])
    result = ''.join(lines)
    parsed = tomllib.loads(result)
    for key, value in edits.items():
        if config_value(parsed, key) != value:
            raise ValueError('config_roundtrip_failed:' + key)
    return result


class ConfigManager:
    def __init__(self, home, state):
        self.home, self.state = Path(home), Path(state)
        self.path = self.home / 'config.toml'
        self.catalog = self.state / 'managed-models.json'
        self.journal = self.state / 'config-ownership.json'

    def apply(self, catalog, visible):
        raw = self.path.read_bytes() if self.path.exists() else b''
        text = raw.decode('utf-8-sig')
        parsed = tomllib.loads(text)
        journal = read_json(self.journal)
        current_path = parsed.get('model_catalog_json')
        if current_path and Path(current_path).resolve() != self.catalog.resolve():
            raise ValueError('another_custom_model_catalog_is_active')
        selected = parsed.get('model')
        if selected not in visible:
            selected = LUNA
        effort = parsed.get('model_reasoning_effort', 'medium')
        if effort not in EFFORTS:
            effort = 'medium'
        edits = {'model_catalog_json': str(self.catalog.resolve()), 'model': selected,
                 'model_reasoning_effort': effort, 'desktop.enabled-reasoning-efforts': list(EFFORTS)}
        updated = edit_config(text, edits)
        if not journal:
            self.state.mkdir(parents=True, exist_ok=True)
            atomic_bytes(self.state / 'config-before-install.toml', raw)
            journal = {'original': {k: config_value(parsed, k) for k in edits}, 'last': {}}
        # Write undo journal first, then valid catalog, then atomic config replacement.
        journal['last'] = edits
        atomic_json(self.journal, journal)
        encoded = json.dumps(catalog, ensure_ascii=False, indent=2).encode('utf-8')
        changed = not self.catalog.exists() or self.catalog.read_bytes() != encoded
        if changed:
            atomic_bytes(self.catalog, encoded)
        if updated != text:
            if self.path.exists() and self.path.read_bytes() != raw:
                raise ValueError('config_changed_concurrently')
            atomic_bytes(self.path, updated.encode('utf-8'))
            changed = True
        return changed

    def restore(self):
        journal = read_json(self.journal)
        if not journal:
            return {'restored': [], 'preserved_user_changes': []}
        raw = self.path.read_bytes()
        text = raw.decode('utf-8-sig')
        parsed = tomllib.loads(text)
        edits, skipped = {}, []
        for key, last in journal['last'].items():
            if config_value(parsed, key) == last:
                edits[key] = journal['original'].get(key)
            else:
                skipped.append(key)
        updated = edit_config(text, edits)
        if self.path.read_bytes() != raw:
            raise ValueError('config_changed_concurrently')
        atomic_bytes(self.path, updated.encode('utf-8'))
        # Keep the catalog and backup for recovery; remove ownership only after success.
        self.journal.replace(self.state / ('restored-' + str(time.time_ns()) + '.json'))
        return {'restored': list(edits), 'preserved_user_changes': skipped}
