"""Generate a high-contrast PNG and SVG without uploading the URL to a QR service."""
import json
from pathlib import Path
from PIL import Image, ImageDraw
from reportlab.graphics.barcode.qrencoder import QRCode, QRErrorCorrectLevel

root = Path(__file__).resolve().parent
info = json.loads((root / 'public-link.json').read_text(encoding='utf-8-sig'))
url = info['url']
qr = QRCode(None, QRErrorCorrectLevel.M)
qr.addData(url)
qr.make()
count, quiet, scale = qr.getModuleCount(), 4, 24
size = (count + 2 * quiet) * scale
img = Image.new('RGB', (size, size), 'white')
draw = ImageDraw.Draw(img)
rectangles = []
for row in range(count):
    for col in range(count):
        if qr.isDark(row, col):
            x, y = (col + quiet) * scale, (row + quiet) * scale
            draw.rectangle((x, y, x + scale - 1, y + scale - 1), fill='#07131F')
            rectangles.append(f'<rect x="{col+quiet}" y="{row+quiet}" width="1" height="1"/>')
output = root.parent / 'output'
output.mkdir(exist_ok=True)
png = output / '智慧药盒_公网体验二维码.png'
svg = output / '智慧药盒_公网体验二维码.svg'
img.save(png)
svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {count+8} {count+8}" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="white"/><g fill="#07131F">'+''.join(rectangles)+'</g></svg>', encoding='utf-8')
(output / '智慧药盒_扫码体验说明.txt').write_text(
    '智慧药盒公网扫码演示\n\n访问地址：' + url + '\n\n'
    '扫码后点击“免注册，体验演示家庭”。每位访客有独立的示例数据。\n'
    '本次为临时公网地址，使用期间电脑须保持联网、服务与连接工具须保持运行。\n'
    '关闭连接工具或电脑休眠后二维码将无法访问；重建连接后可能需要换二维码。\n'
    '仅供软件演示，请勿输入真实个人资料或健康信息。\n', encoding='utf-8')
print(json.dumps({'url':url,'png':str(png),'svg':str(svg),'pixels':size,'modules':count}, ensure_ascii=False))
