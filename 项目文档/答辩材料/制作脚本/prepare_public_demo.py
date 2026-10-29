"""Prepare an isolated, guest-friendly copy for the QR-code demonstration."""
from pathlib import Path
import shutil

SOURCE = Path('E:/学校课程/智慧城市')
WORKSPACE = Path('C:/Users/liuzhanfei/Documents/ChatGPT/智慧药盒')
TARGET = WORKSPACE / 'public-demo'

for folder in ('backend', '微信小程序/assets', 'tools', 'logs'):
    (TARGET / folder).mkdir(parents=True, exist_ok=True)

for name in ('__init__.py', 'main.py', 'domain.py'):
    shutil.copy2(SOURCE / 'backend' / name, TARGET / 'backend' / name)
shutil.copy2(SOURCE / '微信小程序/preview.html', TARGET / '微信小程序/preview.html')
for name in ('demo.css', 'demo.js', 'home-scene.svg', 'home-scene.png'):
    shutil.copy2(SOURCE / '微信小程序/assets' / name, TARGET / '微信小程序/assets' / name)

main_path = TARGET / 'backend/main.py'
main = main_path.read_text(encoding='utf-8')
old = "return database.session(db, db.execute('SELECT id FROM users WHERE phone=?', (DEMO_PHONE,)).fetchone()['id'])"
new = "return database.session(db, database.create_user(db, 'guest-' + uuid.uuid4().hex, '体验家属', secrets.token_urlsafe(24), True))"
if main.count(old) != 1:
    raise RuntimeError('Demo login anchor changed; refusing an unverified patch.')
main_path.write_text(main.replace(old, new), encoding='utf-8')

js_path = TARGET / '微信小程序/assets/demo.js'
js = js_path.read_text(encoding='utf-8')
js = js.replace('本地服务已连接 · 数据自动保存', '演示服务已连接 · 示例数据自动保存')
js = js.replace('后端未连接，请运行“启动演示”', '演示服务暂未连接，请稍后重试')
js = js.replace('后端未连接，请先运行项目中的“启动演示.bat”', '演示服务暂未连接，请稍后刷新重试')
js = js.replace('当前为公共演示家庭，请使用示例资料。', '当前为独立访客演示家庭，请只使用虚构资料。')
js_path.write_text(js, encoding='utf-8')

html_path = TARGET / '微信小程序/preview.html'
html = html_path.read_text(encoding='utf-8')
html = html.replace('先体验演示家庭', '免注册，体验演示家庭')
html = html.replace('演示账号使用示例资料，请勿录入敏感信息。', '扫码演示版：每位访客独立体验，请勿填写真实个人或健康信息。')
html_path.write_text(html, encoding='utf-8')
print('Prepared:', TARGET)
print('Original code and database were not changed or copied.')
