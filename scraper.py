import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import random
from datetime import datetime
from urllib.parse import urlencode

# ========== CONFIGURACIÓN ==========
# URLs a monitorear (puedes añadir más)
URLS = [
    os.getenv("URL_1", ""),
    os.getenv("URL_2", ""),
    os.getenv("URL_3", ""),
]

# Filtrar vacíos
URLS = [u for u in URLS if u]

PRECIO_MAXIMO = float(os.getenv("PRICE_THRESHOLD", "100"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Umbral de descuento para alertar
DESCUENTO_MINIMO = float(os.getenv("DISCOUNT_THRESHOLD", "30"))
# ====================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

def log(mensaje):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {mensaje}")

def detectar_plataforma(url):
    """Detecta si es Amazon, eBay u otra"""
    url_lower = url.lower()
    if 'amazon' in url_lower:
        return 'amazon'
    elif 'ebay' in url_lower:
        return 'ebay'
    elif 'walmart' in url_lower:
        return 'walmart'
    else:
        return 'generica'

def scrapear_pagina(url):
    """Descarga HTML con anti-detección"""
    try:
        log(f"Descargando: {url[:80]}...")
        time.sleep(random.uniform(2, 5))
        
        session = requests.Session()
        response = session.get(url, headers=HEADERS, timeout=20)
        
        log(f"Status: {response.status_code} | Tamaño: {len(response.text)} chars")
        
        if response.status_code in [403, 429]:
            log(f"⚠️ BLOQUEADO ({response.status_code})")
            return None
            
        return BeautifulSoup(response.content, 'html.parser')
        
    except Exception as e:
        log(f"ERROR: {e}")
        return None

# ========== EXTRACTORES POR PLATAFORMA ==========

def extraer_amazon(soup):
    """Extractor específico para Amazon"""
    productos = []
    
    # Amazon usa divs con data-component-type
    items = soup.find_all('div', {'data-component-type': 's-search-result'})
    
    if not items:
        # Fallback: buscar cualquier contenedor de producto
        items = soup.find_all('div', class_=re.compile(r's-result-item|sg-col-inner'))
    
    log(f"Amazon items: {len(items)}")
    
    for item in items:
        try:
            # Nombre
            nombre_elem = item.find('h2')
            if not nombre_elem:
                nombre_elem = item.select_one('span.a-size-medium, span.a-size-base-plus')
            nombre = nombre_elem.get_text(strip=True) if nombre_elem else "Producto Amazon"
            
            # Precio actual
            precio_elem = (
                item.select_one('span.a-price span.a-offscreen') or
                item.select_one('span.a-price .a-offscreen') or
                item.find('span', class_=re.compile(r'a-price'))
            )
            
            if precio_elem:
                # Buscar el span interno con el precio
                precio_span = precio_elem.select_one('span.a-offscreen') or precio_elem
                precio_texto = precio_span.get_text(strip=True) if hasattr(precio_span, 'get_text') else str(precio_span)
            else:
                continue
            
            precio_num = extraer_numero(precio_texto)
            if not precio_num:
                continue
            
            # Precio original (tachado)
            original_elem = item.select_one('span.a-text-price span.a-offscreen')
            original_num = extraer_numero(original_elem.get_text()) if original_elem else None
            
            # Rating
            rating_elem = item.select_one('span.a-icon-alt')
            rating = None
            if rating_elem:
                rating_match = re.search(r'([\d.]+)\s*out of', rating_elem.get_text())
                if rating_match:
                    rating = float(rating_match.group(1))
            
            # URL del producto
            link_elem = item.select_one('h2 a, a.a-link-normal')
            product_url = ""
            if link_elem and link_elem.get('href'):
                href = link_elem['href']
                if href.startswith('/'):
                    product_url = f"https://www.amazon.com{href}"
                else:
                    product_url = href
            
            descuento = calcular_descuento(original_num, precio_num)
            
            productos.append({
                'nombre': nombre[:150],
                'precio': precio_num,
                'precio_original': original_num,
                'descuento_pct': descuento,
                'rating': rating,
                'plataforma': 'Amazon',
                'url': product_url or "https://www.amazon.com"
            })
            
        except Exception as e:
            continue
    
    return productos

def extraer_ebay(soup):
    """Extractor específico para eBay"""
    productos = []
    
    # eBay usa múltiples estructuras
    items = soup.select('li.s-item') or soup.select('[data-testid="item"]')
    
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
                # Limpiar "Nuevo anuncio" u otros prefijos
                nombre_texto = nombre_elem.get_text(strip=True)
                nombre = re.sub(r'^(New Listing|Nuevo anuncio)\s*', '', nombre_texto)
            
            if not nombre or nombre == "Shop on eBay":
                continue
            
            # Precio
            precio_elem = (
                item.select_one('.s-item__price .ux-textspandit') or
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
            shipping = ""
            if shipping_elem:
                shipping = shipping_elem.get_text(strip=True)
            
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

def extraer_generico(soup):
    """Extractor genérico para cualquier otra página"""
    productos = []
    
    # Selectores comunes universales
    selectores_items = [
        '.product-item', '.product', '.item', '.offer',
        '[data-testid="product"]', '.grid-item', '.listing',
        '.s-result-item', '.search-result'
    ]
    
    items = []
    for selector in selectores_items:
        items = soup.select(selector)
        if items:
            log(f"Selector genérico encontrado: {selector} ({len(items)} items)")
            break
    
    if not items:
        # Último intento: buscar elementos con precios
        items = soup.find_all(string=re.compile(r'\$\d+'))
        items = [item.parent for item in items[:20]]
        log(f"Fallback por precios: {len(items)} items")
    
    for item in items:
        try:
            nombre_elem = (
                item.select_one('h2, h3, h4, .title, .name') or
                item.find(['h2', 'h3', 'h4'])
            )
            nombre = nombre_elem.get_text(strip=True) if nombre_elem else "Producto"
            
            precio_elem = item.find(string=re.compile(r'\$[\d,]+\.?\d*'))
            if precio_elem:
                precio_num = extraer_numero(precio_elem)
            else:
                continue
            
            if not precio_num:
                continue
            
            productos.append({
                'nombre': nombre[:150],
                'precio': precio_num,
                'precio_original': None,
                'descuento_pct': 0,
                'plataforma': 'Otra',
                'url': URLS[0] if URLS else ""
            })
            
        except:
            continue
    
    return productos

# ========== FUNCIONES COMUNES ==========

def extraer_numero(texto):
    """Extrae el primer número con $ de un texto"""
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
    # Sin símbolo $
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

def filtrar_ofertas(productos):
    """Filtra productos que cumplan criterios"""
    ofertas = []
    for p in productos:
        precio = p.get('precio', 0)
        descuento = p.get('descuento_pct', 0)
        
        # Criterio 1: Precio bajo
        if precio > 0 and precio < PRECIO_MAXIMO:
            ofertas.append(p)
        # Criterio 2: Gran descuento
        elif descuento >= DESCUENTO_MINIMO:
            ofertas.append(p)
    
    return ofertas

def enviar_telegram(mensaje):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log(f"Telegram no configurado")
        log(mensaje[:300])
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML"
        }, timeout=15)
        log(f"Telegram: {r.status_code}")
    except Exception as e:
        log(f"Error Telegram: {e}")

def formatear_alerta(ofertas_por_plataforma):
    if not ofertas_por_plataforma:
        return None
    
    msg = "🔥 <b>OFERTAS ENCONTRADAS</b> 🔥\n\n"
    
    for plataforma, ofertas in ofertas_por_plataforma.items():
        msg += f"📌 <b>{plataforma}</b> ({len(ofertas)} ofertas)\n"
        msg += "─" * 30 + "\n"
        
        for o in ofertas[:5]:  # Máx 5 por plataforma
            desc = f" (-{o['descuento_pct']}%)" if o.get('descuento_pct') else ""
            rating = f" ⭐{o['rating']}" if o.get('rating') else ""
            
            msg += f"• <b>{o['nombre'][:80]}</b>\n"
            msg += f"  💰 ${o['precio']:.2f}{desc}{rating}\n"
            
            if o.get('precio_original'):
                msg += f"  ~~${o['precio_original']:.2f}~~\n"
            if o.get('shipping'):
                msg += f"  🚚 {o['shipping']}\n"
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
        historial = historial[-50:]  # Mantener últimos 50 registros
        
        with open('historial.json', 'w') as f:
            json.dump(historial, f, indent=2)
    except Exception as e:
        log(f"Error historial: {e}")

# ========== MAIN ==========

def procesar_url(url):
    """Procesa una URL y devuelve productos"""
    plataforma = detectar_plataforma(url)
    log(f"Plataforma detectada: {plataforma}")
    
    soup = scrapear_pagina(url)
    if not soup:
        return []
    
    # Router por plataforma
    if plataforma == 'amazon':
        return extraer_amazon(soup)
    elif plataforma == 'ebay':
        return extraer_ebay(soup)
    else:
        return extraer_generico(soup)

def main():
    log("=" * 60)
    log("AGENTE MULTI-PÁGINA INICIADO")
    log(f"URLs a monitorear: {len(URLS)}")
    log(f"Umbral precio: ${PRECIO_MAXIMO}")
    log(f"Umbral descuento: {DESCUENTO_MINIMO}%")
    log("=" * 60)
    
    if not URLS:
        log("❌ No hay URLs configuradas")
        enviar_telegram("❌ Error: No hay URLs configuradas en los secrets")
        return
    
    todos_productos = []
    ofertas_por_plataforma = {}
    
    for url in URLS:
        log(f"\n--- Procesando: {url[:60]}... ---")
        productos = procesar_url(url)
        
        if productos:
            plataforma = productos[0].get('plataforma', 'Desconocida')
            todos_productos.extend(productos)
            
            # Filtrar ofertas de esta URL
            ofertas = filtrar_ofertas(productos)
            if ofertas:
                ofertas_por_plataforma[plataforma] = ofertas
                log(f"✅ {plataforma}: {len(productos)} productos, {len(ofertas)} ofertas")
            else:
                log(f"ℹ️ {plataforma}: {len(productos)} productos, 0 ofertas")
        else:
            log(f"❌ No se pudieron extraer productos")
    
    # Guardar historial
    guardar_historial(todos_productos)
    
    # Enviar alerta
    mensaje = formatear_alerta(ofertas_por_plataforma)
    if mensaje:
        enviar_telegram(mensaje)
        log(f"\n✅ Alerta enviada con ofertas")
    else:
        resumen = f"ℹ️ Revisión completada. {len(todos_productos)} productos revisados. Sin ofertas que cumplan criterios."
        enviar_telegram(resumen)
        log(f"\nℹ️ Sin ofertas que reportar")
    
    log("\n" + "=" * 60)
    log("FIN")
    log("=" * 60)

if __name__ == "__main__":
    main()
