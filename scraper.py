import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import random
from datetime import datetime

# ========== CONFIGURACIÓN ==========
URLS = [u for u in [
    os.getenv("URL_1", ""),
    os.getenv("URL_2", ""),
    os.getenv("URL_3", ""),
] if u]

PRECIO_MAXIMO = float(os.getenv("PRICE_THRESHOLD", "50"))
DESCUENTO_MINIMO = float(os.getenv("DISCOUNT_THRESHOLD", "30"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
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
    url_lower = url.lower()
    if 'amazon' in url_lower:
        return 'amazon'
    elif 'ebay' in url_lower:
        return 'ebay'
    else:
        return 'generica'

def scrapear_pagina(url):
    try:
        log(f"Descargando: {url[:70]}...")
        time.sleep(random.uniform(2, 5))
        
        session = requests.Session()
        response = session.get(url, headers=HEADERS, timeout=20)
        
        log(f"Status: {response.status_code} | {len(response.text)} chars")
        
        if response.status_code in [403, 429]:
            log(f"⚠️ BLOQUEADO ({response.status_code})")
            return None
            
        return
