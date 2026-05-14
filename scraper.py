import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime

# ========== CONFIGURACIÓN ==========
URL = os.getenv("TARGET_URL", "https://www.example.com/ofertas")
PRECIO_MAXIMO = float(os.getenv("PRICE_THRESHOLD", "100"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")  # Opcional, para Qwen
# ====================================

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0'
}

def log(mensaje):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {mensaje}")

def scrapear_pagina():
    """Descarga el HTML de la página objetivo"""
    try:
        log(f"Descargando: {URL}")
        r = requests.get(URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
        log(f"Descargado: {len(r.text)} caracteres")
        return BeautifulSoup(r.content, 'html.parser')
    except Exception as e:
        log(f"ERROR al descargar: {e}")
        return None

def extraer_con_css(soup):
    """
    Intenta extraer productos con selectores CSS comunes.
    Ajusta estos selectores según la página que monitorees.
    """
    productos = []
    
    # Selectores comunes en tiendas online (ajusta según tu página)
    selectores = [
        '.product-item', '.product', '.item', '.offer',
        '[data-testid="product"]', '.s-result-item',
        '.grid-item', '.listing', '.card'
    ]
    
    items = []
    for selector in selectores:
        items = soup.select(selector)
        if items:
            log(f"Selector encontrado: {selector} ({len(items)} items)")
            break
    
    if not items:
        log("No se encontraron items con selectores CSS. Intentando fallback...")
        # Fallback: buscar cualquier elemento con precio
        texto_completo = soup.get_text()
        return None, texto_completo
    
    for item in items:
        try:
            # Intenta múltiples selectores para nombre
            nombre_elem = (
                item.select_one('.product-name, .title, h2, h3, .name, [data-testid="product-title"]')
                or item.find(['h2', 'h3', 'h4'])
            )
            nombre = nombre_elem.text.strip() if nombre_elem else "Sin nombre"
            
            # Intenta múltiples selectores para precio
            precio_elem = item.select_one(
                '.price, .current-price, .sale-price, .offer-price, '
                '[data-testid="price"], .a-price-whole, .amount'
            )
            precio_texto = precio_elem.text.strip() if precio_elem else ""
            
            # Extraer número del precio
            precio_num = extraer_numero(precio_texto)
            
            # Precio original (para calcular descuento)
            original_elem = item.select_one(
                '.original-price, .was-price, .old-price, .list-price, .strike'
            )
            original_num = extraer_numero(original_elem.text) if original_elem else None
            
            if precio_num and precio_num > 0:
                descuento = calcular_descuento(original_num, precio_num)
                productos.append({
                    'nombre': nombre[:100],
                    'precio': precio_num,
                    'precio_original': original_num,
                    'descuento_pct': descuento,
                    'url': URL
                })
                
        except Exception as e:
            continue
    
    return productos, None

def extraer_numero(texto):
    """Extrae el primer número con decimales de un texto"""
    if not texto:
        return None
    # Busca patrones como $99.99, 99,99 €, USD 100, etc.
    patrones = [
        r'\$[\s]*([\d,]+\.?\d*)',
        r'([\d,]+\.?\d*)\s*\$',
        r'€[\s]*([\d,]+\.?\d*)',
        r'USD\s*([\d,]+\.?\d*)',
        r'([\d,]+\.?\d*)'
    ]
    for patron in patrones:
        match = re.search(patron, texto.replace(',', ''))
        if match:
            try:
                return float(match.group(1))
            except:
                continue
    return None

def calcular_descuento(original, actual):
    """Calcula porcentaje de descuento"""
    if original and original > actual:
        return round((1 - actual/original) * 100, 1)
    return 0

def extraer_con_qwen(html_texto):
    """
    Úsalo solo si CSS falla. Llama a Qwen 3.5 0.8B vía DashScope.
    Cuesta ~$0.02 por millón de tokens.
    """
    if not DASHSCOPE_API_KEY:
        log("No hay API key de Qwen. Saltando extracción con IA.")
        return []
    
    try:
        log("Usando Qwen 3.5 para extraer datos...")
        prompt = f"""Extrae de este HTML los productos en oferta. 
        Devuélvelo SOLO como JSON válido con formato:
        [{{"nombre": "...", "precio": 99.99, "precio_original": 149.99}}]
        
        HTML (primeros 4000 chars):
        {html_texto[:4000]}
        """
        
        response = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
            headers={
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen2.5-0.5b-instruct",
                "input": {
                    "messages": [{"role": "user", "content": prompt}]
                },
                "parameters": {"result_format": "message"}
            },
            timeout=30
        )
        
        resultado = response.json()
        contenido = resultado['output']['choices'][0]['message']['content']
        
        # Extraer JSON del texto
        json_match = re.search(r'\[.*\]', contenido, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        
    except Exception as e:
        log(f"Error con Qwen: {e}")
    
    return []

def filtrar_ofertas(productos):
    """Filtra productos que cumplan el criterio de oferta"""
    ofertas = []
    for p in productos:
        if p['precio'] < PRECIO_MAXIMO:
            ofertas.append(p)
        elif p.get('descuento_pct', 0) > 30:
            ofertas.append(p)
    return ofertas

def enviar_telegram(mensaje):
    """Envía alerta a Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("No configurado Telegram. Mensaje:")
        log(mensaje)
        return
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML"
        }, timeout=10)
        log(f"Telegram enviado: {r.status_code}")
    except Exception as e:
        log(f"Error Telegram: {e}")

def formatear_alerta(ofertas):
    """Formatea el mensaje de alerta"""
    if not ofertas:
        return None
    
    msg = "🔥 <b>OFERTAS ENCONTRADAS</b> 🔥\n\n"
    for o in ofertas[:10]:  # Máximo 10
        desc = f" (-{o['descuento_pct']}%)" if o.get('descuento_pct') else ""
        msg += f"• <b>{o['nombre']}</b>\n"
        msg += f"  💰 ${o['precio']:.2f}{desc}\n"
        if o.get('precio_original'):
            msg += f"  ~~${o['precio_original']:.2f}~~\n"
        msg += "\n"
    
    msg += f"🔗 <a href='{URL}'>Ver página</a>"
    return msg

def guardar_historial(productos):
    """Guarda precios para tracking histórico"""
    try:
        historial = []
        if os.path.exists('historial.json'):
            with open('historial.json', 'r') as f:
                historial = json.load(f)
        
        historial.append({
            'fecha': datetime.now().isoformat(),
            'productos': productos
        })
        
        # Mantener solo últimos 30 días
        historial = historial[-100:]
        
        with open('historial.json', 'w') as f:
            json.dump(historial, f, indent=2)
            
    except Exception as e:
        log(f"Error guardando historial: {e}")

def main():
    log("=" * 50)
    log("AGENTE DE OFERTAS INICIADO")
    log("=" * 50)
    
    # 1. Scrapear
    soup = scrapear_pagina()
    if not soup:
        enviar_telegram("❌ Error al descargar la página")
        return
    
    # 2. Extraer datos (primero CSS, luego Qwen si falla)
    productos, fallback_texto = extraer_con_css(soup)
    
    if productos is None:
        log("CSS falló. Intentando con Qwen...")
        productos = extraer_con_qwen(fallback_texto)
    
    log(f"Productos extraídos: {len(productos)}")
    
    # 3. Guardar historial
    guardar_historial(productos)
    
    # 4. Filtrar ofertas
    ofertas = filtrar_ofertas(productos)
    log(f"Ofertas detectadas: {len(ofertas)}")
    
    # 5. Enviar alerta
    mensaje = formatear_alerta(ofertas)
    if mensaje:
        enviar_telegram(mensaje)
        log("✅ Alerta enviada")
    else:
        log("ℹ️ No hay ofertas que reportar")
    
    log("=" * 50)
    log("FIN")
    log("=" * 50)

if __name__ == "__main__":
    main()
