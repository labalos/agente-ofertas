import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import random
from datetime import datetime

# ========== CONFIGURACIÓN ==========
URL = os.getenv("TARGET_URL", "https://www.walmart.com/search/?query=Electronics")
PRECIO_MAXIMO = float(os.getenv("PRICE_THRESHOLD", "100"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
# ====================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Cache-Control': 'max-age=0',
}

def log(mensaje):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {mensaje}")

def scrapear_pagina():
    try:
        log(f"Descargando: {URL}")
        time.sleep(random.uniform(2, 5))
        session = requests.Session()
        session.get('https://www.walmart.com', headers=HEADERS, timeout=15)
        time.sleep(random.uniform(1, 3))
        response = session.get(URL, headers=HEADERS, timeout=20)
        log(f"Status: {response.status_code}")
        log(f"Tamaño: {len(response.text)} caracteres")
        
        if response.status_code in [403, 429]:
            log(f"⚠️ BLOQUEADO por Walmart ({response.status_code})")
            return None
            
        return BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        log(f"ERROR: {e}")
        return None

def extraer_numero(texto):
    if not texto:
        return None
    patrones = [r'\$[\s]*([\d,]+\.?\d*)', r'([\d,]+\.?\d*)\s*\$']
    for patron in patrones:
        match = re.search(patron, texto.replace(',', ''))
        if match:
            try:
                return float(match.group(1))
            except:
                continue
    return None

def calcular_descuento(original, actual):
    if original and original > actual:
        return round((1 - actual/original) * 100, 1)
    return 0

def extraer_con_css(soup):
    productos = []
    if not soup:
        return None, None
    
    items = soup.select('[data-testid]') or soup.select('[data-automation-id]') or soup.find_all('div', class_=re.compile(r'search-result|product|item'))
    log(f"Items encontrados: {len(items)}")
    
    if not items:
        return None, soup.get_text()[:5000]
    
    for item in items:
        try:
            precio_elem = (
                item.select_one('[data-automation-id="product-price"] span') or
                item.select_one('[data-testid="price"]') or
                item.find('span', string=re.compile(r'\$[\d,]+'))
            )
            if not precio_elem:
                continue
                
            precio_num = extraer_numero(precio_elem.text.strip())
            if not precio_num:
                continue
            
            nombre_elem = (
                item.select_one('[data-automation-id="product-title"]') or
                item.select_one('[data-testid="product-title"]') or
                item.find('a', href=re.compile(r'/ip/'))
            )
            nombre = nombre_elem.text.strip() if nombre_elem else "Producto Walmart"
            
            original_elem = item.find('span', class_=re.compile(r'strike|original|was'))
            original_num = extraer_numero(original_elem.text) if original_elem else None
            
            descuento = calcular_descuento(original_num, precio_num)
            
            productos.append({
                'nombre': nombre[:120],
                'precio': precio_num,
                'precio_original': original_num,
                'descuento_pct': descuento,
                'url': URL
            })
        except:
            continue
    
    log(f"Productos extraídos: {len(productos)}")
    return productos, None

def extraer_con_qwen(html_texto):
    if not DASHSCOPE_API_KEY:
        log("No hay API key de Qwen.")
        return []
    try:
        log("Usando Qwen...")
        prompt = f"Extrae productos con nombre y precio del HTML:\n{html_texto[:4000]}"
        response = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
            headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"},
            json={"model": "qwen2.5-0.5b-instruct", "input": {"messages": [{"role": "user", "content": prompt}]}, "parameters": {"result_format": "message"}},
            timeout=30
        )
        resultado = response.json()
        contenido = resultado['output']['choices'][0]['message']['content']
        json_match = re.search(r'\[.*\]', contenido, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        log(f"Error Qwen: {e}")
    return []

def filtrar_ofertas(productos):
    ofertas = []
    for p in productos:
        if p['precio'] < PRECIO_MAXIMO:
            ofertas.append(p)
        elif p.get('descuento_pct', 0) > 30:
            ofertas.append(p)
    return ofertas

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log(f"Telegram no configurado. Mensaje: {mensaje[:200]}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}, timeout=10)
        log(f"Telegram: {r.status_code}")
    except Exception as e:
        log(f"Error Telegram: {e}")

def formatear_alerta(ofertas):
    if not ofertas:
        return None
    msg = "🔥 <b>OFERTAS WALMART</b> 🔥\n\n"
    for o in ofertas[:10]:
        desc = f" (-{o['descuento_pct']}%)" if o.get('descuento_pct') else ""
        msg += f"• <b>{o['nombre']}</b>\n"
        msg += f"  💰 ${o['precio']:.2f}{desc}\n"
        if o.get('precio_original'):
            msg += f"  ~~${o['precio_original']:.2f}~~\n"
        msg += "\n"
    msg += f"🔗 <a href='{URL}'>Ver en Walmart</a>"
    return msg

def guardar_historial(productos):
    try:
        historial = []
        if os.path.exists('historial.json'):
            with open('historial.json', 'r') as f:
                historial = json.load(f)
        historial.append({'fecha': datetime.now().isoformat(), 'productos': productos})
        historial = historial[-100:]
        with open('historial.json', 'w') as f:
            json.dump(historial, f, indent=2)
    except Exception as e:
        log(f"Error historial: {e}")

def main():
    log("=" * 50)
    log("AGENTE WALMART INICIADO")
    log("=" * 50)
    
    soup = scrapear_pagina()
    if not soup:
        enviar_telegram("❌ Walmart bloqueó la conexión. Intenta más tarde.")
        return
    
    productos, fallback = extraer_con_css(soup)
    if productos is None:
        log("CSS falló. Intentando Qwen...")
        productos = extraer_con_qwen(fallback or soup.get_text())
    
    guardar_historial(productos or [])
    
    ofertas = filtrar_ofertas(productos or [])
    log(f"Ofertas: {len(ofertas)}")
    
    mensaje = formatear_alerta(ofertas)
    if mensaje:
        enviar_telegram(mensaje)
        log("✅ Alerta enviada")
    else:
        log("ℹ️ Sin ofertas")
    
    log("=" * 50)
    log("FIN")

if __name__ == "__main__":
    main()
