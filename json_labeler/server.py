import sys
import io
# 修复 Windows 控制台编码问题
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except:
        pass

import http.server
import socketserver
import copy
import datetime
import hashlib
import json
import os
import shutil
import sys
import argparse
import signal
import tempfile
import threading
import time
import socket
from urllib.parse import parse_qs, quote, unquote, urlparse

# 默认端口
DEFAULT_PORT = 5000
SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
ALLOWED_LABELS = {"", "pass", "fail"}
DEFAULT_ANNOTATED_FILENAME = "annotated_all.json"
DEFAULT_PASS_FILENAME = "accepted_pass.json"
DEFAULT_FAIL_FILENAME = "rejected_fail.json"
DEFAULT_SESSION_ID = "default"
MAX_PAGE_SIZE = 200
PAGE_CACHE_RADIUS = 1

# 全局变量
server_instance = None


def get_default_bind_host():
    """
    Windows 默认只监听本机，Linux 默认监听所有网卡，方便远程访问。
    """
    return '127.0.0.1' if sys.platform == 'win32' else '0.0.0.0'


def get_display_host(bind_host):
    """
    仅用于打印访问地址：
    - 本机绑定地址直接显示
    - 0.0.0.0 / :: 时，尽量推断一个可访问的本机 IP
    """
    if bind_host not in ('0.0.0.0', '::', ''):
        return bind_host

    # 优先尝试通过 UDP 连接推断对外网卡 IP（不需要真的发包）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith('127.'):
                return ip
        finally:
            s.close()
    except:
        pass

    # 兜底：hostname 解析
    try:
        hostname_ip = socket.gethostbyname(socket.gethostname())
        if hostname_ip and not hostname_ip.startswith('127.'):
            return hostname_ip
    except:
        pass

    return 'localhost'


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/api/health', '/api/shutdown'):
            self.handle_api()
        elif parsed.path == '/image':
            query = parse_qs(parsed.query)
            self.serve_image_path(query.get('path', [''])[0])
        elif parsed.path in ('/', '/index.html'):
            self.serve_static_file('index.html')
        elif parsed.path == '/static/app.js':
            self.serve_static_file(os.path.join('static', 'app.js'))
        elif parsed.path == '/static/style.css':
            self.serve_static_file(os.path.join('static', 'style.css'))
        else:
            self.send_error(404, 'Not Found')

    def do_POST(self):
        parsed = urlparse(self.path)
        routes = {
            '/api/load': api_load,
            '/api/page': api_page,
            '/api/label': api_label,
            '/api/export': api_export,
        }
        handler = routes.get(parsed.path)
        if not handler:
            self.write_json({'success': False, 'error': 'Unknown endpoint'}, status=404)
            return

        try:
            self.write_json(handler(self.read_json_body()))
        except Exception as e:
            self.write_json({'success': False, 'error': str(e)}, status=400)

    def handle_api(self):
        parsed = urlparse(self.path)
        path = parsed.path

        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        try:
            if path == '/api/health':
                result = {'status': 'ok', 'port': server_instance.server_address[1] if server_instance else DEFAULT_PORT}
            elif path == '/api/shutdown':
                self.handle_shutdown()
                result = {'success': True, 'message': '服务器正在关闭'}
            else:
                result = {'success': False, 'error': 'Unknown endpoint'}

            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            import traceback
            self.wfile.write(json.dumps({'error': str(e), 'traceback': traceback.format_exc()}, ensure_ascii=False).encode('utf-8'))

    def serve_image_path(self, raw_path):
        img_path = safe_path(raw_path)

        if not img_path or '..' in img_path:
            self.send_error(403, 'Forbidden')
            return

        if not is_valid_image_file(img_path):
            self.send_error(404, _image_error(img_path) or 'Image not found')
            return

        ext = os.path.splitext(img_path)[1].lower()
        mime_types = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.png': 'image/png', '.gif': 'image/gif',
            '.webp': 'image/webp', '.bmp': 'image/bmp',
        }
        content_type = mime_types.get(ext, 'application/octet-stream')

        try:
            with open(img_path, 'rb') as f:
                content = f.read()
        except Exception as e:
            self.send_error(500, str(e))
            return

        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', len(content))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content)

    def serve_image(self):
        img_path = self.path[5:]
        img_path = unquote(img_path)

        # 兼容 Windows 和 Linux 的路径处理
        if sys.platform == 'win32':
            img_path = img_path.replace('/', '\\')
            if img_path.startswith('\\') and len(img_path) > 2 and img_path[2] == ':':
                img_path = img_path[1:]
        else:
            if not img_path.startswith('/') and os.path.exists('/' + img_path):
                img_path = '/' + img_path

        print(f'[DEBUG] 请求图片路径: {img_path}')
        sys.stdout.flush()

        if '..' in img_path:
            self.send_error(403, 'Forbidden')
            return

        if not os.path.exists(img_path) or not os.path.isfile(img_path):
            print(f'[ERROR] 图片不存在：{img_path}')
            sys.stdout.flush()
            self.send_error(404, 'Image not found')
            return

        ext = os.path.splitext(img_path)[1].lower()
        mime_types = {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.png': 'image/png', '.gif': 'image/gif',
            '.webp': 'image/webp', '.bmp': 'image/bmp',
        }
        content_type = mime_types.get(ext, 'application/octet-stream')

        try:
            with open(img_path, 'rb') as f:
                content = f.read()

            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', len(content))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            print(f'[ERROR] 读取图片失败：{e}')
            sys.stdout.flush()
            self.send_error(500, str(e))

    def serve_file(self, filepath):
        ext = os.path.splitext(filepath)[1].lower()
        mime_types = {
            '.html': 'text/html; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.json': 'application/json; charset=utf-8',
        }

        content_type = mime_types.get(ext, 'application/octet-stream')

        with open(filepath, 'rb') as f:
            content = f.read()

        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', len(content))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content)

    def serve_static_file(self, relative_path):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        filepath = os.path.normpath(os.path.join(base_dir, relative_path))
        if not filepath.startswith(base_dir) or not os.path.isfile(filepath):
            self.send_error(404, 'Not Found')
            return
        self.serve_file(filepath)

    def read_json_body(self):
        length = int(self.headers.get('Content-Length') or '0')
        if length == 0:
            return {}
        data = json.loads(self.rfile.read(length).decode('utf-8'))
        if not isinstance(data, dict):
            raise ValueError('JSON body must be an object')
        return data

    def write_json(self, payload, status=200):
        content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(content))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content)

    def handle_shutdown(self):
        global server_instance
        print('[INFO] 收到关闭请求')
        sys.stdout.flush()
        if server_instance:
            threading.Thread(target=server_instance.shutdown, daemon=True).start()
            server_instance = None


def safe_path(path_str):
    if not path_str:
        return None

    if not isinstance(path_str, str):
        path_str = str(path_str)

    decoded = unquote(path_str)
    decoded = decoded.replace('%5C', '\\').replace('%2F', '/')
    normalized = os.path.normpath(decoded)

    return normalized


def parse_target_dirs(data):
    if not isinstance(data, dict):
        return []

    raw_values = []
    list_value = data.get("target_dirs", [])
    if isinstance(list_value, list):
        raw_values.extend(list_value)
    elif isinstance(list_value, str):
        raw_values.append(list_value)

    text_value = data.get("target_dirs_text", "")
    if isinstance(text_value, str) and text_value.strip():
        raw_values.extend(text_value.replace(";", "\n").replace(",", "\n").splitlines())

    parsed = []
    seen = set()
    for value in raw_values:
        if isinstance(value, str):
            value = value.strip()
        path = safe_path(value)
        if not path:
            continue
        folded = os.path.normcase(path)
        if folded in seen:
            continue
        seen.add(folded)
        parsed.append(path)
    return parsed


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def read_json_records(json_path):
    json_path = safe_path(json_path)
    if not json_path or not os.path.exists(json_path):
        raise FileNotFoundError(f'JSON file does not exist: {json_path}')
    if not os.path.isfile(json_path):
        raise ValueError(f'Not a file: {json_path}')

    with open(json_path, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError('JSON file content must be a list')
    return data


def _record_path_value(record, field):
    if not isinstance(record, dict):
        return ''
    value = record.get(field, '')
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return str(value)


def _has_required_path_fields(record):
    if not isinstance(record, dict):
        return False
    for field in ('file_name', 'cond_1', 'cond_2'):
        value = record.get(field)
        if not isinstance(value, str) or not value:
            return False
    return True


def make_sample_key(record):
    parts = [
        _record_path_value(record, 'file_name'),
        _record_path_value(record, 'cond_1'),
        _record_path_value(record, 'cond_2'),
    ]
    return hashlib.sha1('\n'.join(parts).encode('utf-8')).hexdigest()


def sample_key_for_record(record, index=None):
    if _has_required_path_fields(record):
        return make_sample_key(record)

    raw = repr(record)
    raw_hash = hashlib.sha1(raw.encode('utf-8', errors='replace')).hexdigest()
    index_part = 'unknown' if index is None else str(index)
    return f'invalid:{index_part}:{raw_hash}'


def make_group_key(record, index=None):
    basename = os.path.basename(_record_path_value(record, 'file_name'))
    parts = [
        basename,
        _record_path_value(record, 'cond_1'),
        _record_path_value(record, 'cond_2'),
        _record_path_value(record, 'prompt'),
    ]
    if any(parts):
        return hashlib.sha1('\n'.join(parts).encode('utf-8')).hexdigest()

    raw = repr(record)
    raw_hash = hashlib.sha1(raw.encode('utf-8', errors='replace')).hexdigest()
    index_part = 'unknown' if index is None else str(index)
    return f'invalid-group:{index_part}:{raw_hash}'


def expanded_target_record(record, target_path):
    if isinstance(record, dict):
        expanded = copy.deepcopy(record)
    else:
        expanded = {'_invalid_record': copy.deepcopy(record)}
    expanded['file_name'] = target_path
    return expanded


def default_sidecar_path(input_json_path):
    input_json_path = safe_path(input_json_path)
    root, _ = os.path.splitext(input_json_path)
    return os.path.normpath(f'{root}.labels.json')


def sanitize_export_filename(name, default_name=None):
    fallback = default_name or 'export.json'
    value = str(name or '').replace('\\', '/').split('/')[-1]
    unsafe_chars = '<>:"/\\|?*'
    sanitized = ''.join('_' if ch in unsafe_chars or ord(ch) < 32 else ch for ch in value)
    sanitized = sanitized.strip(' .')

    if not sanitized:
        if default_name and name != default_name:
            return sanitize_export_filename(default_name)
        sanitized = fallback

    if not sanitized.lower().endswith('.json'):
        sanitized = f'{sanitized}.json'
    return sanitized


def validate_export_filenames(annotated_name, pass_name, fail_name):
    names = [
        sanitize_export_filename(annotated_name, DEFAULT_ANNOTATED_FILENAME),
        sanitize_export_filename(pass_name, DEFAULT_PASS_FILENAME),
        sanitize_export_filename(fail_name, DEFAULT_FAIL_FILENAME),
    ]
    folded = [name.lower() for name in names]
    if len(set(folded)) != len(folded):
        raise ValueError('Export filenames must be unique')
    return tuple(names)


def atomic_write_json(path, payload):
    path = os.path.normpath(path)
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    temp_path = None

    try:
        fd, temp_path = tempfile.mkstemp(
            prefix=f'.{os.path.basename(path)}.',
            suffix='.tmp',
            dir=directory,
        )
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


def stage_json_file(path, payload):
    path = os.path.normpath(path)
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    temp_path = None

    try:
        fd, temp_path = tempfile.mkstemp(
            prefix=f'.{os.path.basename(path)}.',
            suffix='.tmp',
            dir=directory,
        )
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        return temp_path
    except Exception:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


def backup_existing_file(path):
    if not os.path.exists(path):
        return None

    directory = os.path.dirname(path) or '.'
    fd, backup_path = tempfile.mkstemp(
        prefix=f'.{os.path.basename(path)}.',
        suffix='.bak',
        dir=directory,
    )
    os.close(fd)
    try:
        shutil.copy2(path, backup_path)
    except Exception:
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except OSError:
                pass
        raise
    return backup_path


class ExportRollbackError(RuntimeError):
    def __init__(self, backup_paths):
        self.backup_paths = backup_paths
        joined_paths = ', '.join(backup_paths)
        super().__init__(f'Export failed and rollback restore failed; backups preserved at: {joined_paths}')


def empty_sidecar(source_file=""):
    source_mtime = None
    if source_file and os.path.exists(source_file):
        source_mtime = os.path.getmtime(source_file)
    return {
        'source_file': source_file,
        'source_mtime': source_mtime,
        'updated_at': now_iso(),
        'labels': {},
        'groups': {},
    }


def _corrupt_sidecar_path(sidecar_path):
    root, _ = os.path.splitext(sidecar_path)
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    candidate = f'{root}.corrupt-{timestamp}.json'
    if not os.path.exists(candidate):
        return candidate

    counter = 1
    while True:
        candidate = f'{root}.corrupt-{timestamp}-{counter}.json'
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def load_sidecar(sidecar_path, source_file=""):
    sidecar_path = os.path.normpath(sidecar_path)
    if not os.path.exists(sidecar_path):
        return empty_sidecar(source_file)

    try:
        with open(sidecar_path, 'r', encoding='utf-8-sig') as f:
            sidecar = json.load(f)
        if not isinstance(sidecar, dict) or not isinstance(sidecar.get('labels'), dict):
            raise ValueError('Invalid sidecar shape')
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        os.replace(sidecar_path, _corrupt_sidecar_path(sidecar_path))
        return empty_sidecar(source_file)

    labels = {}
    for sample_key, entry in sidecar.get('labels', {}).items():
        if not isinstance(sample_key, str) or not isinstance(entry, dict):
            continue
        human_label = entry.get('human_label', '')
        if human_label not in ALLOWED_LABELS:
            continue
        labels[sample_key] = {
            'human_label': human_label,
            'updated_at': entry.get('updated_at', ''),
        }

    sidecar['labels'] = labels
    groups = {}
    for group_key, entry in sidecar.get('groups', {}).items():
        if not isinstance(group_key, str) or not isinstance(entry, dict):
            continue
        if entry.get('reviewed') is True:
            groups[group_key] = {
                'reviewed': True,
                'updated_at': entry.get('updated_at', ''),
            }

    sidecar['groups'] = groups
    sidecar.setdefault('source_file', source_file)
    sidecar.setdefault('source_mtime', os.path.getmtime(source_file) if source_file and os.path.exists(source_file) else None)
    sidecar.setdefault('updated_at', now_iso())
    return sidecar


def save_sidecar(sidecar_path, sidecar):
    sidecar = copy.deepcopy(sidecar)
    sidecar['updated_at'] = now_iso()
    atomic_write_json(sidecar_path, sidecar)
    return sidecar


def load_jsonl_records(jsonl_path):
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()

    if not content:
        return []

    # 兼容 JSON array 和标准 jsonl 两种格式
    if content[0] == '[':
        data = json.loads(content)
        if not isinstance(data, list):
            raise ValueError('JSON 文件内容必须是 list')
        return data

    records = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception as e:
            raise ValueError(f'第 {line_no} 行 JSON 解析失败：{e}')
    return records


def to_img_url(path_value):
    path_value = safe_path(path_value)
    if not path_value:
        return None
    return f"/image?path={quote(path_value, safe='')}"


def is_valid_image_file(path_value):
    if not path_value or not os.path.exists(path_value) or not os.path.isfile(path_value):
        return False
    ext = os.path.splitext(path_value)[1].lower()
    return ext in SUPPORTED_EXTENSIONS


def _image_error(path_value):
    if not path_value:
        return 'missing path'
    if not os.path.exists(path_value):
        return 'file does not exist'
    if not os.path.isfile(path_value):
        return 'not a file'
    ext = os.path.splitext(path_value)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return 'unsupported image type'
    return None


def normalize_record_for_item(record, index):
    is_record = isinstance(record, dict)
    item = copy.deepcopy(record) if is_record else {}
    source_path = safe_path(_record_path_value(record, 'cond_1'))
    reference_path = safe_path(_record_path_value(record, 'cond_2'))
    target_path = safe_path(_record_path_value(record, 'file_name'))
    image_fields = {
        'cond_1': source_path,
        'cond_2': reference_path,
        'file_name': target_path,
    }

    item.update({
        'index': index,
        'sample_key': sample_key_for_record(record, index),
        'source_path': source_path,
        'reference_path': reference_path,
        'target_path': target_path,
        'source': to_img_url(source_path),
        'reference': to_img_url(reference_path),
        'target': to_img_url(target_path),
        'image_errors': {},
    })

    for field, path_value in image_fields.items():
        error = _image_error(path_value)
        if error:
            item['image_errors'][field] = error

    if not is_record:
        item['image_errors']['record'] = f'Record at index {index} is not an object'

    return item


def _valid_target_dirs(target_dirs):
    valid = []
    invalid = []
    for target_dir in target_dirs:
        path = safe_path(target_dir)
        if path and os.path.isdir(path):
            valid.append(path)
        elif path:
            invalid.append(path)
    return valid, invalid


def build_target_dir_indexes(target_dirs):
    indexes = []
    for target_dir in target_dirs:
        files = {}
        try:
            with os.scandir(target_dir) as entries:
                for entry in entries:
                    if not entry.is_file():
                        continue
                    filename = entry.name
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        files[filename] = os.path.normpath(entry.path)
        except OSError:
            files = {}

        indexes.append({
            'path': target_dir,
            'name': os.path.basename(target_dir),
            'files': files,
        })
    return indexes


def expand_records_to_groups_from_indexes(records, target_indexes=None, start_index=0):
    target_indexes = target_indexes or []
    groups = []
    for index, record in enumerate(records, start_index):
        basename = os.path.basename(_record_path_value(record, 'file_name'))
        group_key = make_group_key(record, index)
        shared = normalize_record_for_item(record, index)
        group = {
            'index': index,
            'group_key': group_key,
            'basename': basename,
            'prompt': record.get('prompt', '') if isinstance(record, dict) else '',
            'source_path': shared.get('source_path', ''),
            'reference_path': shared.get('reference_path', ''),
            'source': shared.get('source'),
            'reference': shared.get('reference'),
            'image_errors': {
                key: value for key, value in shared.get('image_errors', {}).items()
                if key in ('cond_1', 'cond_2', 'record')
            },
            'missing_target_dirs': [],
            'targets': [],
        }

        if target_indexes:
            for target_index in target_indexes:
                target_dir = target_index['path']
                target_path = target_index['files'].get(basename, '') if basename else ''
                if target_path:
                    target_record = expanded_target_record(record, target_path)
                    target_item = normalize_record_for_item(target_record, index)
                    target_item['group_key'] = group_key
                    target_item['target_index'] = len(group['targets'])
                    target_item['target_dir'] = target_dir
                    target_item['target_dir_name'] = target_index['name']
                    target_item['record'] = target_record
                    group['targets'].append(target_item)
                else:
                    group['missing_target_dirs'].append(target_dir)
        else:
            target_record = copy.deepcopy(record)
            target_item = normalize_record_for_item(target_record, index)
            target_item['group_key'] = group_key
            target_item['target_index'] = 0
            target_item['target_dir'] = os.path.dirname(_record_path_value(record, 'file_name'))
            target_item['target_dir_name'] = os.path.basename(target_item['target_dir'])
            target_item['record'] = target_record
            group['targets'].append(target_item)

        groups.append(group)

    return groups


def expand_records_to_groups(records, target_dirs=None):
    target_dirs = target_dirs or []
    valid_dirs, invalid_dirs = _valid_target_dirs(target_dirs)
    if target_dirs and not valid_dirs:
        joined = ', '.join(invalid_dirs or target_dirs)
        raise ValueError(f'No valid target directories: {joined}')

    target_indexes = build_target_dir_indexes(valid_dirs) if valid_dirs else []
    return expand_records_to_groups_from_indexes(records, target_indexes)


def target_records_for_record(record, index, target_indexes=None):
    target_indexes = target_indexes or []
    if target_indexes:
        basename = os.path.basename(_record_path_value(record, 'file_name'))
        if not basename:
            return []
        targets = []
        for target_index in target_indexes:
            target_path = target_index['files'].get(basename, '')
            if target_path:
                targets.append(expanded_target_record(record, target_path))
        return targets
    return [copy.deepcopy(record)]


def any_target_matches(records, target_indexes=None):
    target_indexes = target_indexes or []
    if not target_indexes:
        return bool(records)
    for index, record in enumerate(records):
        if target_records_for_record(record, index, target_indexes):
            return True
    return False


def build_items(records, sidecar):
    items = []
    labels = {}
    sidecar_labels = sidecar.get('labels', {}) if isinstance(sidecar, dict) else {}

    for index, record in enumerate(records):
        item = normalize_record_for_item(record, index)
        items.append(item)
        sidecar_entry = sidecar_labels.get(item['sample_key'])
        if not isinstance(sidecar_entry, dict):
            continue
        human_label = sidecar_entry.get('human_label', '')
        if human_label not in ALLOWED_LABELS:
            continue
        labels[item['sample_key']] = {
            'human_label': human_label,
            'updated_at': sidecar_entry.get('updated_at', ''),
        }

    return items, labels


def labels_for_items(items, sidecar):
    labels = {}
    sidecar_labels = sidecar.get('labels', {}) if isinstance(sidecar, dict) else {}

    for item in items:
        sidecar_entry = sidecar_labels.get(item.get('sample_key', ''))
        if not isinstance(sidecar_entry, dict):
            continue
        human_label = sidecar_entry.get('human_label', '')
        if human_label not in ALLOWED_LABELS:
            continue
        labels[item['sample_key']] = {
            'human_label': human_label,
            'updated_at': sidecar_entry.get('updated_at', ''),
        }

    return labels


def labels_for_records(records, sidecar):
    labels = {}
    sidecar_labels = sidecar.get('labels', {}) if isinstance(sidecar, dict) else {}

    for index, record in enumerate(records):
        sample_key = sample_key_for_record(record, index)
        sidecar_entry = sidecar_labels.get(sample_key)
        if not isinstance(sidecar_entry, dict):
            continue
        human_label = sidecar_entry.get('human_label', '')
        if human_label not in ALLOWED_LABELS:
            continue
        labels[sample_key] = {
            'human_label': human_label,
            'updated_at': sidecar_entry.get('updated_at', ''),
        }

    return labels


def labels_for_groups(groups, sidecar):
    labels = {}
    sidecar_labels = sidecar.get('labels', {}) if isinstance(sidecar, dict) else {}

    for group in groups:
        for target in group.get('targets', []):
            sample_key = target.get('sample_key', '')
            sidecar_entry = sidecar_labels.get(sample_key)
            if not isinstance(sidecar_entry, dict):
                continue
            human_label = sidecar_entry.get('human_label', '')
            if human_label not in ALLOWED_LABELS:
                continue
            labels[sample_key] = {
                'human_label': human_label,
                'updated_at': sidecar_entry.get('updated_at', ''),
            }

    return labels


def page_bounds(total, page, page_size):
    page_size = max(1, min(MAX_PAGE_SIZE, int(page_size or 20)))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(total_pages, int(page or 1)))
    start = (page - 1) * page_size
    end = min(total, start + page_size)
    return page, page_size, total_pages, start, end


def build_page(records, sidecar, page=1, page_size=20):
    page, page_size, total_pages, start, end = page_bounds(len(records), page, page_size)
    items = [normalize_record_for_item(record, index) for index, record in enumerate(records[start:end], start)]
    return {
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "items": items,
        "labels": labels_for_items(items, sidecar),
    }


def page_groups(groups, sidecar, page=1, page_size=20):
    page, page_size, total_pages, start, end = page_bounds(len(groups), page, page_size)
    current = groups[start:end]
    sidecar_groups = sidecar.get('groups', {}) if isinstance(sidecar, dict) else {}
    return {
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "groups": current,
        "labels": labels_for_groups(current, sidecar),
        "group_progress": {
            group.get('group_key', ''): sidecar_groups.get(group.get('group_key', ''), {})
            for group in current
        },
    }


def materialize_group_page(records, target_indexes, page=1, page_size=20):
    page, page_size, total_pages, start, end = page_bounds(len(records), page, page_size)
    return {
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "groups": expand_records_to_groups_from_indexes(records[start:end], target_indexes, start),
    }


def labels_for_dataset(records, target_indexes, sidecar):
    labels = {}
    sidecar_labels = sidecar.get('labels', {}) if isinstance(sidecar, dict) else {}

    for index, record in enumerate(records):
        for target_record in target_records_for_record(record, index, target_indexes):
            sample_key = sample_key_for_record(target_record, index)
            sidecar_entry = sidecar_labels.get(sample_key)
            if not isinstance(sidecar_entry, dict):
                continue
            human_label = sidecar_entry.get('human_label', '')
            if human_label not in ALLOWED_LABELS:
                continue
            labels[sample_key] = {
                'human_label': human_label,
                'updated_at': sidecar_entry.get('updated_at', ''),
            }

    return labels


def compute_stats(records, labels):
    passed = 0
    failed = 0

    for index, record in enumerate(records):
        sample_key = sample_key_for_record(record, index)
        entry = labels.get(sample_key, {})
        human_label = entry.get('human_label') if isinstance(entry, dict) else None
        if human_label == 'pass':
            passed += 1
        elif human_label == 'fail':
            failed += 1

    labeled = passed + failed
    total = len(records)
    return {
        'total': total,
        'pass': passed,
        'fail': failed,
        'labeled': labeled,
        'unlabeled': total - labeled,
    }


def compute_group_stats(groups, labels, group_progress):
    groups_total = len(groups)
    groups_reviewed = sum(
        1 for group in groups
        if group_progress.get(group.get('group_key', ''), {}).get('reviewed') is True
    )
    targets_total = 0
    passed = 0
    failed = 0
    unlabeled = 0

    for group in groups:
        for target in group.get('targets', []):
            targets_total += 1
            entry = labels.get(target.get('sample_key', ''), {})
            human_label = entry.get('human_label', '') if isinstance(entry, dict) else ''
            if human_label == 'pass':
                passed += 1
            elif human_label == 'fail':
                failed += 1
            else:
                unlabeled += 1

    return {
        'groups_total': groups_total,
        'groups_reviewed': groups_reviewed,
        'groups_unreviewed': groups_total - groups_reviewed,
        'targets_total': targets_total,
        'pass': passed,
        'fail': failed,
        'unlabeled_as_fail': unlabeled,
    }


def compute_group_stats_for_records(records, target_indexes, labels, group_progress):
    groups_total = len(records)
    groups_reviewed = sum(
        1 for index, record in enumerate(records)
        if group_progress.get(make_group_key(record, index), {}).get('reviewed') is True
    )
    targets_total = 0
    passed = 0
    failed = 0
    unlabeled = 0

    for index, record in enumerate(records):
        for target_record in target_records_for_record(record, index, target_indexes):
            targets_total += 1
            sample_key = sample_key_for_record(target_record, index)
            entry = labels.get(sample_key, {})
            human_label = entry.get('human_label', '') if isinstance(entry, dict) else ''
            if human_label == 'pass':
                passed += 1
            elif human_label == 'fail':
                failed += 1
            else:
                unlabeled += 1

    return {
        'groups_total': groups_total,
        'groups_reviewed': groups_reviewed,
        'groups_unreviewed': groups_total - groups_reviewed,
        'targets_total': targets_total,
        'pass': passed,
        'fail': failed,
        'unlabeled_as_fail': unlabeled,
    }


def apply_label(labels, sample_key, human_label, now=None):
    if human_label not in ALLOWED_LABELS:
        raise ValueError(f'Invalid label: {human_label}')
    labels[sample_key] = {
        'human_label': human_label,
        'updated_at': now or now_iso(),
    }
    return labels[sample_key]


def apply_label_to_sidecar(sidecar, sample_key, group_key, human_label, now=None):
    labels = sidecar.setdefault('labels', {})
    groups = sidecar.setdefault('groups', {})
    label = apply_label(labels, sample_key, human_label, now=now)
    timestamp = label['updated_at']
    if human_label:
        groups[group_key] = {'reviewed': True, 'updated_at': timestamp}
    return label


def compute_group_progress_from_labels(groups, labels, existing_progress=None):
    progress = copy.deepcopy(existing_progress or {})
    for group in groups:
        group_key = group.get('group_key', '')
        if not group_key:
            continue
        if progress.get(group_key, {}).get('reviewed') is True:
            continue
        for target in group.get('targets', []):
            entry = labels.get(target.get('sample_key', ''), {})
            if isinstance(entry, dict) and entry.get('human_label') in ('pass', 'fail'):
                progress[group_key] = {
                    'reviewed': True,
                    'updated_at': entry.get('updated_at', ''),
                }
                break
    return progress


def infer_legacy_group_progress(records, groups, sidecar):
    progress = copy.deepcopy(sidecar.get('groups', {}) if isinstance(sidecar, dict) else {})
    sidecar_labels = sidecar.get('labels', {}) if isinstance(sidecar, dict) else {}

    for index, record in enumerate(records):
        if index >= len(groups):
            break
        group = groups[index]
        group_key = group.get('group_key', '')
        if not group_key or progress.get(group_key, {}).get('reviewed') is True:
            continue
        legacy_key = sample_key_for_record(record, index)
        entry = sidecar_labels.get(legacy_key)
        if isinstance(entry, dict) and entry.get('human_label') in ('pass', 'fail'):
            progress[group_key] = {
                'reviewed': True,
                'updated_at': entry.get('updated_at', ''),
            }

    return progress


def infer_group_progress_for_records(records, target_indexes, sidecar):
    progress = copy.deepcopy(sidecar.get('groups', {}) if isinstance(sidecar, dict) else {})
    sidecar_labels = sidecar.get('labels', {}) if isinstance(sidecar, dict) else {}

    for index, record in enumerate(records):
        group_key = make_group_key(record, index)
        if not group_key or progress.get(group_key, {}).get('reviewed') is True:
            continue

        candidate_records = [record] + target_records_for_record(record, index, target_indexes)
        for candidate in candidate_records:
            sample_key = sample_key_for_record(candidate, index)
            entry = sidecar_labels.get(sample_key)
            if isinstance(entry, dict) and entry.get('human_label') in ('pass', 'fail'):
                progress[group_key] = {
                    'reviewed': True,
                    'updated_at': entry.get('updated_at', ''),
                }
                break

    return progress


def unreviewed_group_at_records(records, group_progress, start_index=0, wrap=False):
    total = len(records)
    if total == 0:
        return None

    limit = total if wrap else max(0, total - start_index)
    for offset in range(limit):
        index = (start_index + offset) % total
        group_key = make_group_key(records[index], index)
        entry = group_progress.get(group_key, {})
        if entry.get('reviewed') is not True:
            return {"group_key": group_key, "index": index}
    return None


def build_export_payloads(records, labels):
    annotated_all = []
    passed = []
    failed = []

    for index, record in enumerate(records):
        sample_key = sample_key_for_record(record, index)
        entry = labels.get(sample_key, {})
        human_label = entry.get('human_label', '') if isinstance(entry, dict) else ''

        if human_label == 'pass':
            if isinstance(record, dict):
                annotated = copy.deepcopy(record)
                annotated['human_label'] = human_label
            else:
                annotated = {
                    '_invalid_record': copy.deepcopy(record),
                    'human_label': human_label,
                }
            annotated_all.append(annotated)
            passed.append(copy.deepcopy(record))
        elif human_label == 'fail':
            if isinstance(record, dict):
                annotated = copy.deepcopy(record)
                annotated['human_label'] = human_label
            else:
                annotated = {
                    '_invalid_record': copy.deepcopy(record),
                    'human_label': human_label,
                }
            annotated_all.append(annotated)
            failed.append(copy.deepcopy(record))

    return annotated_all, passed, failed


def build_export_payloads_from_groups(groups, labels):
    annotated_all = []
    passed = []
    failed = []

    for group in groups:
        for target in group.get('targets', []):
            record = copy.deepcopy(target.get('record', {}))
            entry = labels.get(target.get('sample_key', ''), {})
            human_label = entry.get('human_label', '') if isinstance(entry, dict) else ''
            export_label = human_label if human_label in ('pass', 'fail') else 'fail'

            if isinstance(record, dict):
                annotated = copy.deepcopy(record)
                annotated['human_label'] = export_label
            else:
                annotated = {
                    '_invalid_record': copy.deepcopy(record),
                    'human_label': export_label,
                }

            annotated_all.append(annotated)
            if export_label == 'pass':
                passed.append(copy.deepcopy(record))
            else:
                failed.append(copy.deepcopy(record))

    return annotated_all, passed, failed


def make_empty_state():
    return {
        "input_json_path": "",
        "sidecar_path": "",
        "records": [],
        "groups": [],
        "page_cache": {},
        "cache_page_size": None,
        "target_dirs": [],
        "target_indexes": [],
        "sidecar": empty_sidecar(""),
    }


STATE = make_empty_state()
SESSIONS = {DEFAULT_SESSION_ID: STATE}


def _session_id_from_request(data):
    if not isinstance(data, dict):
        return DEFAULT_SESSION_ID
    session_id = str(data.get("session_id", "")).strip()
    return session_id or DEFAULT_SESSION_ID


def _state_for_request(data):
    session_id = _session_id_from_request(data)
    if session_id == DEFAULT_SESSION_ID:
        SESSIONS[DEFAULT_SESSION_ID] = STATE
        return session_id, STATE
    if session_id not in SESSIONS:
        SESSIONS[session_id] = make_empty_state()
    return session_id, SESSIONS[session_id]


def _current_labels(state=None):
    if state is None:
        state = STATE
    sidecar = state.get("sidecar") if isinstance(state, dict) else {}
    labels = sidecar.get("labels", {}) if isinstance(sidecar, dict) else {}
    if not isinstance(labels, dict):
        labels = {}
        sidecar["labels"] = labels
    return labels


def _current_groups_progress(state=None):
    if state is None:
        state = STATE
    sidecar = state.get("sidecar") if isinstance(state, dict) else {}
    groups = sidecar.get("groups", {}) if isinstance(sidecar, dict) else {}
    if not isinstance(groups, dict):
        groups = {}
        sidecar["groups"] = groups
    return groups


def _loaded_sample_keys(records):
    return {sample_key_for_record(record, index) for index, record in enumerate(records)}


def find_sample_index(records, sample_key):
    for index, record in enumerate(records):
        if sample_key_for_record(record, index) == sample_key:
            return index
    return -1


def find_target_item(groups, sample_key):
    for group in groups:
        for target in group.get('targets', []):
            if target.get('sample_key') == sample_key:
                return target
    return None


def refresh_cached_groups(state):
    cached = []
    for page in sorted(state.get("page_cache", {})):
        cached.extend(state["page_cache"][page].get("groups", []))
    state["groups"] = cached
    return cached


def ensure_group_page_cache(state, requested_page=1, page_size=20):
    records = state.get("records", [])
    target_indexes = state.get("target_indexes", [])
    page, page_size, total_pages, _, _ = page_bounds(len(records), requested_page, page_size)

    if state.get("cache_page_size") != page_size:
        state["page_cache"] = {}
        state["cache_page_size"] = page_size

    wanted_pages = range(
        max(1, page - PAGE_CACHE_RADIUS),
        min(total_pages, page + PAGE_CACHE_RADIUS) + 1,
    )
    wanted_pages = set(wanted_pages)
    page_cache = state.setdefault("page_cache", {})

    for cache_page in wanted_pages:
        if cache_page not in page_cache:
            page_cache[cache_page] = materialize_group_page(records, target_indexes, cache_page, page_size)

    for cache_page in list(page_cache):
        if cache_page not in wanted_pages:
            del page_cache[cache_page]

    refresh_cached_groups(state)
    return page_cache[page]


def unlabeled_at(records, labels, start_index=0, wrap=False):
    total = len(records)
    if total == 0:
        return None

    limit = total if wrap else max(0, total - start_index)
    for offset in range(limit):
        index = (start_index + offset) % total
        sample_key = sample_key_for_record(records[index], index)
        entry = labels.get(sample_key, {})
        human_label = entry.get('human_label') if isinstance(entry, dict) else ''
        if not human_label:
            return {"sample_key": sample_key, "index": index}
    return None


def unreviewed_group_at(groups, group_progress, start_index=0, wrap=False):
    total = len(groups)
    if total == 0:
        return None

    limit = total if wrap else max(0, total - start_index)
    for offset in range(limit):
        index = (start_index + offset) % total
        group = groups[index]
        entry = group_progress.get(group.get('group_key', ''), {})
        if entry.get('reviewed') is not True:
            return {"group_key": group.get('group_key', ''), "index": index}
    return None


def api_load(data):
    session_id, state = _state_for_request(data)
    input_json_path = safe_path(data.get("input_json_path") if isinstance(data, dict) else "")
    if not input_json_path:
        raise ValueError("input_json_path is required")

    target_dirs = parse_target_dirs(data)
    records = read_json_records(input_json_path)
    sidecar_path = default_sidecar_path(input_json_path)
    sidecar = load_sidecar(sidecar_path, input_json_path)
    valid_dirs, invalid_dirs = _valid_target_dirs(target_dirs)
    if target_dirs and not valid_dirs:
        joined = ', '.join(invalid_dirs or target_dirs)
        raise ValueError(f'No valid target directories: {joined}')
    target_indexes = build_target_dir_indexes(valid_dirs) if valid_dirs else []
    if target_dirs and not any_target_matches(records, target_indexes):
        raise ValueError('No target images matched input JSON basenames in the provided target directories')
    labels = labels_for_dataset(records, target_indexes, sidecar)
    sidecar['groups'] = infer_group_progress_for_records(records, target_indexes, sidecar)
    sidecar = save_sidecar(sidecar_path, sidecar)
    group_progress = sidecar.get('groups', {})

    state.update({
        "input_json_path": input_json_path,
        "sidecar_path": sidecar_path,
        "records": records,
        "groups": [],
        "page_cache": {},
        "cache_page_size": None,
        "target_dirs": target_dirs,
        "target_indexes": target_indexes,
        "sidecar": sidecar,
    })

    return {
        "success": True,
        "session_id": session_id,
        "labels": labels,
        "group_progress": group_progress,
        "first_unreviewed_group": unreviewed_group_at_records(records, group_progress),
        "progress_path": sidecar_path,
        "stats": compute_group_stats_for_records(records, target_indexes, labels, group_progress),
    }


def api_page(data):
    session_id, state = _state_for_request(data)
    records = state.get("records", [])
    if not records:
        raise ValueError("No dataset loaded")

    page_data = ensure_group_page_cache(
        state,
        data.get("page", 1) if isinstance(data, dict) else 1,
        data.get("page_size", 20) if isinstance(data, dict) else 20,
    )
    current = page_data.get("groups", [])
    sidecar_groups = _current_groups_progress(state)
    labels = labels_for_groups(current, state.get("sidecar", {}))
    page_data.update({
        "success": True,
        "session_id": session_id,
        "labels": labels,
        "group_progress": {
            group.get('group_key', ''): sidecar_groups.get(group.get('group_key', ''), {})
            for group in current
        },
        "stats": compute_group_stats_for_records(
            records,
            state.get("target_indexes", []),
            _current_labels(state),
            sidecar_groups,
        ),
    })
    return page_data


def api_label(data):
    session_id, state = _state_for_request(data)
    groups = state.get("groups", [])
    sidecar_path = state.get("sidecar_path", "")
    if not groups or not sidecar_path:
        raise ValueError("No dataset loaded")

    sample_key = data.get("sample_key") if isinstance(data, dict) else ""
    target = find_target_item(groups, sample_key)
    if not target:
        raise ValueError("sample_key is not in the loaded dataset")

    human_label = data.get("human_label", "") if isinstance(data, dict) else ""
    label = apply_label_to_sidecar(state["sidecar"], sample_key, target["group_key"], human_label)
    state["sidecar"] = save_sidecar(sidecar_path, state["sidecar"])
    labels = _current_labels(state)
    return {
        "success": True,
        "session_id": session_id,
        "sample_key": sample_key,
        "group_key": target["group_key"],
        "label": label,
        "group_progress": _current_groups_progress(state),
        "stats": compute_group_stats_for_records(
            state.get("records", []),
            state.get("target_indexes", []),
            labels,
            _current_groups_progress(state),
        ),
    }


def api_export(data):
    session_id, state = _state_for_request(data)
    records = state.get("records", [])
    if not records:
        raise ValueError("No dataset loaded")

    export_dir = safe_path(data.get("export_dir") if isinstance(data, dict) else "")
    if not export_dir:
        raise ValueError("export_dir is required")

    annotated_name, pass_name, fail_name = validate_export_filenames(
        data.get("annotated_filename", DEFAULT_ANNOTATED_FILENAME),
        data.get("pass_filename", DEFAULT_PASS_FILENAME),
        data.get("fail_filename", DEFAULT_FAIL_FILENAME),
    )
    groups = expand_records_to_groups_from_indexes(records, state.get("target_indexes", []))
    annotated, passed, failed = build_export_payloads_from_groups(groups, _current_labels(state))
    paths = {
        "annotated": os.path.normpath(os.path.join(export_dir, annotated_name)),
        "pass": os.path.normpath(os.path.join(export_dir, pass_name)),
        "fail": os.path.normpath(os.path.join(export_dir, fail_name)),
    }

    payloads = {
        "annotated": annotated,
        "pass": passed,
        "fail": failed,
    }
    staged = []
    try:
        for key, payload in payloads.items():
            staged.append((paths[key], stage_json_file(paths[key], payload)))
    except Exception:
        for _, temp_path in staged:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        raise

    backups = []
    try:
        for final_path, _ in staged:
            backups.append((final_path, backup_existing_file(final_path)))
    except Exception:
        for _, temp_path in staged:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        for _, backup_path in backups:
            if backup_path and os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
        raise

    promoted = []
    try:
        for final_path, temp_path in staged:
            os.replace(temp_path, final_path)
            promoted.append(final_path)
    except Exception as promotion_error:
        for final_path in promoted:
            if os.path.exists(final_path):
                try:
                    os.remove(final_path)
                except OSError:
                    pass
        unrestored_backups = []
        for final_path, backup_path in backups:
            if backup_path and os.path.exists(backup_path):
                try:
                    os.replace(backup_path, final_path)
                except OSError:
                    unrestored_backups.append(backup_path)
        for _, temp_path in staged:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
        for _, backup_path in backups:
            if backup_path and backup_path not in unrestored_backups and os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except OSError:
                    pass
        if unrestored_backups:
            raise ExportRollbackError(unrestored_backups) from promotion_error
        raise

    for _, backup_path in backups:
        if backup_path and os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except OSError:
                pass

    return {
        "success": True,
        "session_id": session_id,
        "paths": paths,
        "counts": {
            "annotated": len(annotated),
            "pass": len(passed),
            "fail": len(failed),
        },
    }


def scan_jsonl(jsonl_path_raw):
    jsonl_path = safe_path(jsonl_path_raw)

    if not jsonl_path or not os.path.exists(jsonl_path):
        return {'success': False, 'error': f'jsonl 文件不存在：{jsonl_path}'}

    if not os.path.isfile(jsonl_path):
        return {'success': False, 'error': f'不是文件：{jsonl_path}'}

    try:
        records = load_jsonl_records(jsonl_path)
    except Exception as e:
        return {'success': False, 'error': f'读取 jsonl 失败：{e}'}

    if not records:
        return {'success': False, 'error': 'jsonl 中没有有效记录'}

    groups = []
    for idx, item in enumerate(records):
        if not isinstance(item, dict):
            continue

        src_path = safe_path(item.get('cond_1', ''))
        ref_path = safe_path(item.get('cond_2', ''))
        tgt_path = safe_path(item.get('file_name', ''))

        if not (is_valid_image_file(src_path) and is_valid_image_file(ref_path) and is_valid_image_file(tgt_path)):
            continue

        extra_meta = {k: v for k, v in item.items() if k not in {'cond_1', 'cond_2', 'file_name'}}

        groups.append({
            'id': idx,
            'filename': os.path.basename(tgt_path),
            'source': to_img_url(src_path),
            'reference': to_img_url(ref_path),
            'target': to_img_url(tgt_path),
            'source_path': src_path,
            'reference_path': ref_path,
            'target_path': tgt_path,
            'meta': extra_meta,
        })

    if not groups:
        return {
            'success': False,
            'error': '没有找到有效图片记录，请检查 cond_1 / cond_2 / file_name 是否为存在的图片绝对路径'
        }

    return {'success': True, 'groups': groups}


def handle_export_request(jsonl_path, evaluations_json):
    import base64

    try:
        evaluations = json.loads(base64.b64decode(evaluations_json).decode('utf-8'))

        report_lines = []
        report_lines.append('=' * 50)
        report_lines.append('图片评测报告')
        report_lines.append('=' * 50)
        report_lines.append(f'jsonl 文件: {jsonl_path}')
        report_lines.append('')

        total = len(evaluations)
        passed = sum(1 for v in evaluations.values() if v == 'pass')
        failed = sum(1 for v in evaluations.values() if v == 'fail')

        report_lines.append(f'总计: {total} 组')
        report_lines.append(f'通过: {passed}')
        report_lines.append(f'不通过: {failed}')
        report_lines.append('')
        report_lines.append('=' * 50)
        report_lines.append('详细结果')
        report_lines.append('=' * 50)

        for filename, status in evaluations.items():
            status_text = '通过' if status == 'pass' else '不通过'
            report_lines.append(f'{filename}: {status_text}')

        report_content = '\n'.join(report_lines)

        report_dir = os.path.join(os.getcwd(), 'reports')
        os.makedirs(report_dir, exist_ok=True)

        timestamp = time.strftime('%Y%m%d_%H%M%S')
        report_path = os.path.join(report_dir, f'evaluation_{timestamp}.txt')

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)

        return {'success': True, 'message': f'报告已保存到: {report_path}'}

    except Exception as e:
        return {'success': False, 'error': f'导出失败：{str(e)}'}


def signal_handler(sig, frame):
    print('')
    print('服务器已停止')
    sys.stdout.flush()
    global server_instance
    if server_instance:
        try:
            server_instance.server_close()
        except:
            pass
        server_instance = None
    os._exit(0)


def start_server(port, host=None):
    global server_instance

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    socketserver.TCPServer.allow_reuse_address = True

    bind_host = host or get_default_bind_host()

    try:
        server_instance = socketserver.TCPServer((bind_host, port), Handler)
        display_host = get_display_host(bind_host)

        print('=' * 50)
        print('服务器已启动')
        print(f'   地址: http://{display_host}:{port}')
        print(f'   监听: {bind_host}:{port}')
        print(f'   工作目录: {os.getcwd()}')
        print('   按 Ctrl+C 停止服务器')
        print('=' * 50)
        sys.stdout.flush()

        server_instance.serve_forever()
    except OSError as e:
        if e.errno == 98 or 'address already in use' in str(e).lower():
            print(f'错误: 端口 {port} 已被占用')
            sys.stdout.flush()
        else:
            print(f'错误: 启动失败 - {e}')
            sys.stdout.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        print('')
        print('服务器已停止')
        sys.stdout.flush()
        server_instance = None
        sys.exit(0)


def stop_server(port):
    import urllib.request
    import urllib.error

    try:
        print(f'正在关闭端口 {port} 的服务器...')
        sys.stdout.flush()
        urllib.request.urlopen(f'http://localhost:{port}/api/shutdown', timeout=5)
        print('服务器已关闭')
        sys.stdout.flush()
    except urllib.error.URLError as e:
        print(f'无法连接到服务器: {e}')
        sys.stdout.flush()
    except Exception as e:
        print(f'关闭服务器时出错: {e}')
        sys.stdout.flush()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='图片评测服务器')
    parser.add_argument('-p', '--port', type=int, default=DEFAULT_PORT, help=f'端口 (默认: {DEFAULT_PORT})')
    parser.add_argument('--host', default=None, help='监听地址，例如 0.0.0.0 可供局域网访问')
    parser.add_argument('--stop', action='store_true', help='停止服务器')

    args = parser.parse_args()

    if args.stop:
        stop_server(args.port)
    else:
        start_server(args.port, args.host)
