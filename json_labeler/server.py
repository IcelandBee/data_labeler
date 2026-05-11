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
import json
import os
import sys
import argparse
import signal
import time
import socket
from urllib.parse import unquote

# 默认端口
DEFAULT_PORT = 5000
SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}

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
        if self.path.startswith('/api/'):
            self.handle_api()
        elif self.path.startswith('/img/'):
            self.serve_image()
        else:
            path = self.path.lstrip('/')
            if path == '':
                path = 'index.html'

            if '..' in path:
                self.send_error(403, 'Forbidden')
                return

            if os.path.exists(path) and os.path.isfile(path):
                self.serve_file(path)
            else:
                self.send_error(404, 'Not Found')

    def handle_api(self):
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        try:
            if path == '/api/health':
                result = {'status': 'ok', 'port': server_instance.server_address[1] if server_instance else DEFAULT_PORT}
            elif path == '/api/scan':
                jsonl_path = query.get('jsonl', [''])[0]
                result = scan_jsonl(jsonl_path)
            elif path == '/api/shutdown':
                self.handle_shutdown()
                result = {'success': True, 'message': '服务器正在关闭'}
            elif path == '/api/export':
                jsonl_path = query.get('jsonl', [''])[0]
                evaluations_json = query.get('evaluations', [''])[0]
                result = handle_export_request(jsonl_path, evaluations_json)
            else:
                result = {'error': 'Unknown endpoint'}

            self.wfile.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            import traceback
            self.wfile.write(json.dumps({'error': str(e), 'traceback': traceback.format_exc()}, ensure_ascii=False).encode('utf-8'))

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

    def handle_shutdown(self):
        global server_instance
        print('[INFO] 收到关闭请求')
        sys.stdout.flush()
        if server_instance:
            server_instance.shutdown()
            server_instance = None


def safe_path(path_str):
    if not path_str:
        return None

    decoded = unquote(path_str)
    decoded = decoded.replace('%5C', '\\').replace('%2F', '/')
    normalized = os.path.normpath(decoded)

    return normalized


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
    path_value_url = path_value.replace('\\', '/')
    return f"/img/{path_value_url}"


def is_valid_image_file(path_value):
    if not path_value or not os.path.exists(path_value) or not os.path.isfile(path_value):
        return False
    ext = os.path.splitext(path_value)[1].lower()
    return ext in SUPPORTED_EXTENSIONS


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


def start_server(port):
    global server_instance

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    socketserver.TCPServer.allow_reuse_address = True

    bind_host = get_default_bind_host()

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
    parser.add_argument('--stop', action='store_true', help='停止服务器')

    args = parser.parse_args()

    if args.stop:
        stop_server(args.port)
    else:
        start_server(args.port)
