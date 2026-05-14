import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import random
from datetime import datetime

# ========== CONFIGURACIÓN ==========
URLS = [
    os.getenv("URL_1", ""),
    os.getenv("URL_2", ""),
    os.getenv("URL_3", ""),
    os.getenv("URL_4", ""),
    os.getenv("URL_5", ""),
]

URLS = [u for u in URLS if u]

PRECIO_MAXIMO = float(os.getenv("PRICE_THRESHOLD", "150"))
DESCUENTO_MINIMO = float(os.getenv("DISCOUNT_THRESHOLD", "25"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

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
}

def log(mensaje):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {mensaje}")

def detectar_plataforma(url):
    url_lower = url.lower()
    if 'amazon' in url_lower:
        return 'amazon'
    elif 'ebay' in url_lower:
        return 'ebay'
    elif 'walmart' in url_lower:
        return 'walmart'
    elif 'mammut' in url_lower:
        return 'mammut'
    elif 'wornwear' in url_lower or 'patagonia.com' in url_lower:
        return 'patagonia'
    else:
        return 'rei'

def scrapear_pagina(url):
    try:
        log(f"Descargando: {url[:80]}...")
        time.sleep(random.uniform(1, 3))
        
        session = requests.Session()
        response = session.get(url, headers=HEADERS, timeout=30)
        
        log(f"Status: {response.status_code} | Tamaño: {len(response.text)} chars")
        
        if response.status_code in [403, 429]:
            log(f"⚠️ BLOQUEADO ({response.status_code})")
            return None
            
        return BeautifulSoup(response.content, 'html.parser')
        
    except Exception as e:
        log(f"ERROR al descargar: {e}")
        return None

def extraer_numero(texto):
    if not texto:
        return None
    if hasattr(texto, 'get_text'):
        texto = texto.get_text()
    texto = str(texto)
    
    match = re.search(r'\$[\s]*([\d,]+\.?\d*)', texto.replace(',', ''))
    if match:
        try:
            return float(match.group(1))
        except:
            pass
    
    match = re.search(r'([\d,]+\.?\d*)', texto.replace(',', ''))
    if match:
        try:
            return float(match.group(1))
        except:
            pass
    return None

def calcular_descuento(original, actual):
    if original and original > actual and original > 0:
        return round((1 - actual/original) * 100, 1)
    return 0

def extraer_ebay(soup):
    productos = []
    if not soup:
        return productos
    
    # eBay usa li.s-item
    items = soup.select('li.s-item')
    
    if not items:
        items = soup.find_all('div', class_=re.compile(r's-item|listitem'))
    
    log(f"eBay items: {len(items)}")
    
    for item in items:
        try:
            # Nombre
            nombre_elem = (
                item.select_one('.s-item__title span[role="text"]') or
                item.select_one('.s-item__title') or
                item.select_one('a.s-item__link')
            )
            nombre = ""
            if nombre_elem:
                nombre_texto = nombre_elem.get_text(strip=True)
                nombre = re.sub(r'^(New Listing|Nuevo anuncio)\s*', '', nombre_texto)
            
            if not nombre or nombre == "Shop on eBay":
                continue
            
            # Precio
            precio_elem = (
                item.select_one('.s-item__price') or
                item.select_one('[itemprop="price"]')
            )
            
            if not precio_elem:
                continue
            
            precio_texto = precio_elem.get_text(strip=True)
            precio_num = extraer_numero(precio_texto)
            
            if not precio_num:
                continue
            
            # Precio original
            original_elem = item.select_one('.s-item__original-price, .s-item__trending-price')
            original_num = extraer_numero(original_elem.get_text()) if original_elem else None
            
            # Shipping
            shipping_elem = item.select_one('.s-item__shipping, .s-item__logisticsCost')
            shipping = shipping_elem.get_text(strip=True) if shipping_elem else ""
            
            # Link
            link_elem = item.select_one('a.s-item__link')
            product_url = link_elem['href'] if link_elem and link_elem.get('href') else "https://www.ebay.com"
            
            descuento = calcular_descuento(original_num, precio_num)
            
            productos.append({
                'nombre': nombre[:150],
                'precio': precio_num,
                'precio_original': original_num,
                'descuento_pct': descuento,
                'shipping': shipping,
                'plataforma': 'eBay',
                'url': product_url
            })
            
        except Exception as e:
            continue
    
    return productos

def extraer_mammut(soup):
    productos = []
    if not soup:
        return productos
    
    # GUARDAR HTML PARA DEBUG
    try:
        with open('debug_mammut.html', 'w', encoding='utf-8') as f:
            f.write(str(soup)[:100000])
        log("HTML guardado en debug_mammut.html")
    except Exception as e:
        log(f"Error guardando HTML: {e}")
    
    # Buscar TODOS los enlaces que contienen /p/ (productos)
    links = soup.find_all('a', href=re.compile(r'/p/\d+'))
    log(f"Links a productos encontrados: {len(links)}")
    
    # Mostrar los primeros 3 links para ver estructura
    for i, link in enumerate(links[:3]):
        log(f"Link {i}: {link.get('href', 'N/A')[:80]}")
        # Buscar precio cerca del link
        parent = link.find_parent('div', class_=re.compile(r'.+'))
        if parent:
            precio = parent.find(string=re.compile(r'\$\d+'))
            if precio:
                log(f"  Precio cercano: {precio.strip()[:50]}")
    
    # Intentar extraer productos de los links
    items = []
    for link in links:
        parent = link.find_parent('div', class_=re.compile(r'.+'))
        if parent and parent not in items:
            items.append(parent)
    
    log(f"Mammut items únicos: {len(items)}")
    
    for item in items:
        try:
            # Nombre del producto
            nombre_elem = link.find('span') or link
            nombre = nombre_elem.get_text(strip=True) if hasattr(nombre_elem, 'get_text') else str(nombre_elem)
            
            # Buscar precio en el contenedor padre o abuelo
            precio = None
            for ancestor in [item, item.find_parent(), item.find_parent().find_parent() if item.find_parent() else None]:
                if ancestor:
                    precio_elem = ancestor.find(string=re.compile(r'\$\d[\d,]*\.?\d*'))
                    if precio_elem:
                        precio = extraer_numero(precio_elem)
                        if precio:
                            break
            
            if not precio:
                continue
            
            productos.append({
                'nombre': nombre[:150],
                'precio': precio,
                'precio_original': None,
                'descuento_pct': 0,
                'plataforma': 'Mammut',
                'url': f"https://www.mammut.com{link['href']}" if link.get('href', '').startswith('/') else link.get('href', 'https://www.mammut.com')
            })
            
        except Exception as e:
            continue
    
    return productos

def extraer_patagonia(soup):
    productos = []
    if not soup:
        return productos
    
    # Patagonia Worn Wear usa divs con clase product
    items = soup.find_all('div', class_=re.compile(r'product|product-tile|product-card'))
    
    if not items:
        items = soup.find_all('article') or soup.find_all('li', class_=re.compile(r'product'))
    
    log(f"Patagonia items: {len(items)}")
    
    for item in items:
        try:
            nombre_elem = (
                item.select_one('.product-name') or
                item.select_one('.product-title') or
                item.select_one('h2') or
                item.select_one('h3') or
                item.find('a', href=re.compile(r'/product/|/shop/'))
            )
            nombre = nombre_elem.get_text(strip=True) if nombre_elem else "Producto Patagonia"
            
            precio_elem = (
                item.select_one('.price') or
                item.select_one('.product-price') or
                item.select_one('[data-price]') or
                item.find(string=re.compile(r'\$\d+'))
            )
            
            if not precio_elem:
                continue
            
            precio_num = extraer_numero(precio_elem)
            if not precio_num:
                continue
            
            original_elem = (
                item.select_one('.compare-price') or
                item.select_one('.was-price') or
                item.find('span', class_=re.compile(r'compare|original'))
            )
            original_num = extraer_numero(original_elem) if original_elem else None
            
            descuento = calcular_descuento(original_num, precio_num)
            
            link_elem = item.find('a', href=re.compile(r'/product/|/shop/'))
            product_url = ""
            if link_elem and link_elem.get('href'):
                href = link_elem['href']
                if href.startswith('/'):
                    product_url = f"https://wornwear.patagonia.com{href}"
                else:
                    product_url = href
            
            productos.append({
                'nombre': nombre[:150],
                'precio': precio_num,
                'precio_original': original_num,
                'descuento_pct': descuento,
                'plataforma': 'Patagonia Worn Wear',
                'url': product_url or "https://wornwear.patagonia.com"
            })
            
        except Exception as e:
            continue
    
    return productos

def extraer_rei(soup):
    productos = []
    if not soup:
        return productos
    
    items = soup.find_all('div', {'data-product-id': True})
    if not items:
        items = soup.find_all('div', class_=re.compile(r'search-result|product-tile'))
    
    log(f"REI items: {len(items)}")
    
    for item in items:
        try:
            nombre_elem = (
                item.select_one('a[data-testid="product-link"]') or
                item.select_one('h2 a') or
                item.select_one('.product-title') or
                item.find('a', href=re.compile(r'/product/'))
            )
            nombre = nombre_elem.get_text(strip=True) if nombre_elem else "Producto REI"
            
            precio_elem = (
                item.select_one('span[data-testid="sale-price"]') or
                item.select_one('span.sale-price') or
                item.select_one('.price-current') or
                item.find('span', class_=re.compile(r'price'))
            )
            
            if not precio_elem:
                continue
            
            precio_num = extraer_numero(precio_elem)
            if not precio_num:
                continue
            
            original_elem = (
                item.select_one('span[data-testid="compare-price"]') or
                item.select_one('span.compare-price') or
                item.find('span', class_=re.compile(r'compare|original|was'))
            )
            original_num = extraer_numero(original_elem) if original_elem else None
            
            descuento = calcular_descuento(original_num, precio_num)
            
            productos.append({
                'nombre': nombre[:150],
                'precio': precio_num,
                'precio_original': original_num,
                'descuento_pct': descuento,
                'plataforma': 'REI',
                'url': 'https://www.rei.com'
            })
            
        except Exception as e:
            continue
    
    return productos

def filtrar_ofertas(productos):
    ofertas = []
    for p in productos:
        precio = p.get('precio', 0)
        descuento = p.get('descuento_pct', 0)
        
        if precio > 0 and precio < PRECIO_MAXIMO:
            ofertas.append(p)
        elif descuento >= DESCUENTO_MINIMO:
            ofertas.append(p)
    
    return ofertas

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram no configurado")
        return
    
    if not mensaje or mensaje.strip() == "":
        mensaje = "ℹ️ Revisión completada. Sin ofertas que cumplan criterios."
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje[:4000],
            "parse_mode": "HTML"
        }, timeout=15)
        log(f"Telegram: {r.status_code}")
        if r.status_code != 200:
            log(f"Telegram error: {r.text[:200]}")
    except Exception as e:
        log(f"Error Telegram: {e}")

def formatear_alerta(ofertas_por_plataforma):
    if not ofertas_por_plataforma:
        return None
    
    msg = "🔥 <b>OFERTAS ENCONTRADAS</b> 🔥\n\n"
    
    for plataforma, ofertas in ofertas_por_plataforma.items():
        msg += f"📌 <b>{plataforma}</b> ({len(ofertas)} ofertas)\n"
        msg += "─" * 30 + "\n"
        
        for o in ofertas[:5]:
            desc = f" (-{o['descuento_pct']}%)" if o.get('descuento_pct') else ""
            shipping = f" 🚚 {o['shipping']}" if o.get('shipping') else ""
            
            msg += f"• <b>{o['nombre'][:80]}</b>\n"
            msg += f"  💰 ${o['precio']:.2f}{desc}{shipping}\n"
            if o.get('precio_original'):
                msg += f"  ~~${o['precio_original']:.2f}~~\n"
            msg += "\n"
        
        msg += "\n"
    
    return msg

def guardar_historial(todos_productos):
    try:
        historial = []
        if os.path.exists('historial.json'):
            with open('historial.json', 'r') as f:
                historial = json.load(f)
        
        historial.append({
            'fecha': datetime.now().isoformat(),
            'productos': todos_productos
        })
        historial = historial[-50:]
        
        with open('historial.json', 'w') as f:
            json.dump(historial, f, indent=2)
    except Exception as e:
        log(f"Error historial: {e}")

def procesar_url(url):
    plataforma = detectar_plataforma(url)
    log(f"Plataforma: {plataforma}")
    
    soup = scrapear_pagina(url)
    if not soup:
        return []
    
    if plataforma == 'ebay':
        return extraer_ebay(soup)
    elif plataforma == 'mammut':
        return extraer_mammut(soup)
    elif plataforma == 'patagonia':
        return extraer_patagonia(soup)
    elif plataforma == 'rei':
        return extraer_rei(soup)
    else:
        return extraer_rei(soup)

def main():
    log("=" * 60)
    log("AGENTE MULTI-PÁGINA INICIADO")
    log(f"URLs: {len(URLS)}")
    log(f"Umbral precio: ${PRECIO_MAXIMO}")
    log(f"Umbral descuento: {DESCUENTO_MINIMO}%")
    log("=" * 60)
    
    if not URLS:
        log("❌ No hay URLs configuradas")
        enviar_telegram("❌ Error: No hay URLs configuradas")
        return
    
    todos_productos = []
    ofertas_por_plataforma = {}
    
    for url in URLS:
        log(f"\n--- Procesando: {url[:60]}... ---")
        productos = procesar_url(url)
        
        if productos:
            plataforma = productos[0].get('plataforma', 'Desconocida')
            todos_productos.extend(productos)
            
            ofertas = filtrar_ofertas(productos)
            if ofertas:
                ofertas_por_plataforma[plataforma] = ofertas
                log(f"✅ {plataforma}: {len(productos)} productos, {len(ofertas)} ofertas")
            else:
                log(f"ℹ️ {plataforma}: {len(productos)} productos, 0 ofertas")
        else:
            log(f"❌ No se pudieron extraer productos")
    
    guardar_historial(todos_productos)
    
    mensaje = formatear_alerta(ofertas_por_plataforma)
    if mensaje:
        enviar_telegram(mensaje)
        log(f"\n✅ Alerta enviada")
    else:
        resumen = f"ℹ️ Revisión completada. {len(todos_productos)} productos revisados. Sin ofertas que cumplan criterios."
        enviar_telegram(resumen)
        log(f"\nℹ️ Sin ofertas")
    
    log("\n" + "=" * 60)
    log("FIN")
    log("=" * 60)

if __name__ == "__main__":
    main()
