import subprocess
import os
from jinja2 import Environment, FileSystemLoader
from datetime import datetime

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "generated_pdfs")
os.makedirs(OUT_DIR, exist_ok=True)
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))

def generate_invoice_pdf(order, product):
    tpl = env.get_template("invoice_template.html")
    html = tpl.render(order=order, product=product, date=datetime.utcnow())
    out_filename = f"invoice_{order.order_id_str}.pdf"
    out_path = os.path.join(OUT_DIR, out_filename)
    # write html temp
    tmp_html = out_path + ".html"
    with open(tmp_html, "w", encoding="utf-8") as f:
        f.write(html)
    # call wkhtmltopdf
    subprocess.run(["wkhtmltopdf", tmp_html, out_path], check=True)
    os.remove(tmp_html)
    return out_path
