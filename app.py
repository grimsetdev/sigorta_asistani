import os
import math
import pickle
import sqlite3
from datetime import datetime
import streamlit as st
from pypdf import PdfReader
from google import genai
from PIL import Image

# --- Sayfa Ayarları ---
st.set_page_config(page_title="Grimset AI | Sigorta Otomasyonu", page_icon="🏢", layout="wide")

# --- API ANAHTARI VE GÜVENLİK AYARLARI ---
api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")

if not api_key:
    st.error("Lütfen Gemini API anahtarını Streamlit Secrets veya Ortam Değişkeni olarak ekleyin!")
    st.stop()

client = genai.Client(api_key=api_key)
VISION_MODEL = 'gemini-2.5-flash'
TEXT_MODEL = 'gemini-2.5-flash'

HAFIZA_DOSYASI = "vektor_hafizasi.pkl"
BELGELER_KLASORU = "belgeler"

# --- 1. AŞAMA: GELİŞMİŞ CRM VE VADE TAKİP VERİTABANI ---
def veritabani_kur():
    conn = sqlite3.connect('grimset_crm.db')
    c = conn.cursor()
    # Eski kayıt tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS ruhsat_kayitlari
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  tarih TEXT,
                  ayiklanan_veri TEXT)''')
    # YENİ: Vade takipli müşteri portföy tablosu
    c.execute('''CREATE TABLE IF NOT EXISTS musteri_portfoyu
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  musteri_adi TEXT,
                  telefon TEXT,
                  plaka TEXT,
                  vade_tarihi DATE,
                  eklenme_tarihi TEXT,
                  ocr_verisi TEXT)''')
    conn.commit()
    conn.close()

veritabani_kur()

# --- Arka Plan Fonksiyonları (Vektör & OCR) ---
def metni_vektore_cevir(metin):
    response = client.models.embed_content(
        model='gemini-embedding-001',
        contents=metin
    )
    return response.embeddings[0].values

def benzerlik_hesapla(v1, v2):
    dot_product = sum(a * b for a, b in zip(v1, v2))
    magnitude1 = math.sqrt(sum(a * a for a in v1))
    magnitude2 = math.sqrt(sum(a * a for a in v2))
    if magnitude1 * magnitude2 == 0: return 0
    return dot_product / (magnitude1 * magnitude2)

def hafizayi_olustur_ve_kaydet():
    if not os.path.exists(BELGELER_KLASORU):
        os.makedirs(BELGELER_KLASORU)
        st.error(f"'{BELGELER_KLASORU}' klasörü oluşturuldu. İçine PDF ekleyin.")
        st.stop()

    pdf_dosyalari = [f for f in os.listdir(BELGELER_KLASORU) if f.endswith('.pdf')]
    if not pdf_dosyalari:
        st.error("Klasörde hiç PDF bulunamadı!")
        st.stop()

    tam_metin = ""
    for dosya in pdf_dosyalari:
        dosya_yolu = os.path.join(BELGELER_KLASORU, dosya)
        reader = PdfReader(dosya_yolu)
        for sayfa in reader.pages:
            if sayfa.extract_text():
                tam_metin += f"\n[Kaynak: {dosya}]\n" + sayfa.extract_text() + "\n"

    chunk_size = 1000
    parcalar = [tam_metin[i:i+chunk_size] for i in range(0, len(tam_metin), chunk_size)]

    veritabani = []
    progress_bar = st.progress(0)
    for i, parca in enumerate(parcalar):
        if len(parca.strip()) > 50: 
            vektor = metni_vektore_cevir(parca)
            veritabani.append({"metin": parca, "vektor": vektor})
        progress_bar.progress((i + 1) / len(parcalar))
    progress_bar.empty()
    
    with open(HAFIZA_DOSYASI, 'wb') as f:
        pickle.dump(veritabani, f)
        
    return veritabani

@st.cache_resource
def veritabani_yukle():
    if os.path.exists(HAFIZA_DOSYASI):
        with open(HAFIZA_DOSYASI, 'rb') as f:
            return pickle.load(f)
    else:
        with st.spinner("PDF'ler taranıyor, bu işlem sadece bir kez yapılır..."):
            return hafizayi_olustur_ve_kaydet()

def ruhsat_oku(gorsel_dosya):
    gorsel = Image.open(gorsel_dosya)
    prompt = """Sen analitik bir OCR asistanısın. Gönderilen fotoğrafı (Türkiye araç ruhsatı) analiz et. 
SADECE aşağıdaki alanları ayıkla ve temiz bir liste halinde ver. Eğer bir alan okunmuyorsa boş bırak.
- Plaka:
- T.C. Kimlik No:
- Şasi No (VIN):
- Motor No:
- Marka/Model:
- Trafiğe Çıkış Tarihi:
Asla yorum yapma, sadece verileri döndür."""

    try:
        response = client.models.generate_content(
            model=VISION_MODEL,
            contents=[prompt, gorsel]
        )
        return response.text
    except Exception as e:
        st.error(f"Görsel işleme hatası: {str(e)}")
        return None

def teklif_karsilastir(gorsel_1, gorsel_2):
    img1 = Image.open(gorsel_1)
    img2 = Image.open(gorsel_2)
    
    prompt = """Sen Grimset Studio'nun en yetenekli sigorta satış uzmanısın. Ekte iki farklı sigorta şirketine ait teklif fotoğrafları var. 
Bu iki teklifi detaylıca incele ve müşteriye sunmak üzere şu formatta ikna edici bir karşılaştırma raporu hazırla:
1. Fiyat Karşılaştırması: (Hangi teklif daha uygun?)
2. Teminat Farkları: (İkame araç, cam kırılması, ihtiyari mali mesuliyet gibi farklar neler?)
3. Muafiyet ve Dezavantajlar: (Ucuz olanın gizli bir muafiyeti/şartı var mı?)
4. Satış Kapatma Tavsiyesi: (Danışmanımız müşteriye hangi teklifi, hangi cümlelerle satmalı?)
Raporu profesyonel, net ve kolay okunabilir bir dille yaz."""

    try:
        response = client.models.generate_content(
            model=VISION_MODEL,
            contents=[prompt, img1, img2]
        )
        return response.text
    except Exception as e:
        st.error(f"Karşılaştırma hatası: {str(e)}")
        return None

db = veritabani_yukle()

# --- YAN MENÜ ---
st.sidebar.image("https://images.squarespace-cdn.com/content/v1/6055d01a61b2383be553b1b6/bd6d8e20-94d0-4e36-b552-6d2c4b574229/grimset+copy+copy+logo.png?format=1500w", width=150)
st.sidebar.title("Sistem Modülleri")
sayfa = st.sidebar.radio("Modül Seçimi:", ["Ana Sayfa (Müşteri Kayıt)", "Teklif Karşılaştırma", "Yönetici Paneli (Alarm)"])
st.sidebar.markdown("---")
st.sidebar.caption("Grimset Studio © 2026")

if sayfa == "Ana Sayfa (Müşteri Kayıt)":
    # --- ANA SAYFA ---
    sol_panel, sag_panel = st.columns([1, 2], gap="large")

    with sol_panel:
        st.title("🏢 Sigorta Otomasyonu")
        st.markdown("---")
        
        st.subheader("📄 Ruhsat Ayıklama ve Kayıt")
        
        # Okunan verinin formda kaybolmaması için session_state kullanımı
        if "son_ocr" not in st.session_state:
            st.session_state.son_ocr = None
            
        yuklenen_gorsel = st.file_uploader("Ruhsat fotoğrafı yükle...", type=["jpg", "jpeg", "png"])
        
        if yuklenen_gorsel:
            st.image(yuklenen_gorsel, use_container_width=True)
            if st.button("Belgeden Verileri Ayıkla", use_container_width=True):
                with st.spinner("Gemini Vision çalışıyor..."):
                    ayiklanan_veri = ruhsat_oku(yuklenen_gorsel)
                    if ayiklanan_veri:
                        st.session_state.son_ocr = ayiklanan_veri
                        st.success("Veriler başarıyla ayıklandı!")
                        
        if st.session_state.son_ocr:
            st.text_area("Ayıklanan Bilgiler", value=st.session_state.son_ocr, height=200)
            
            st.markdown("### 💾 CRM Vade Takvimine Ekle")
            with st.form("crm_kayit_formu"):
                m_adi = st.text_input("Müşteri Adı Soyadı")
                m_tel = st.text_input("Telefon Numarası")
                m_plaka = st.text_input("Araç Plakası")
                m_vade = st.date_input("Poliçe Yenileme / Vade Tarihi")
                
                if st.form_submit_button("Sisteme Kaydet", use_container_width=True):
                    if m_adi and m_plaka:
                        conn = sqlite3.connect('grimset_crm.db')
                        c = conn.cursor()
                        zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        c.execute("INSERT INTO musteri_portfoyu (musteri_adi, telefon, plaka, vade_tarihi, eklenme_tarihi, ocr_verisi) VALUES (?, ?, ?, ?, ?, ?)", 
                                  (m_adi, m_tel, m_plaka, m_vade, zaman, st.session_state.son_ocr))
                        conn.commit()
                        conn.close()
                        st.success(f"{m_adi} kişisi vade takvimine başarıyla eklendi!")
                        st.session_state.son_ocr = None # Kayıt sonrası temizle
                    else:
                        st.warning("Lütfen en azından Müşteri Adı ve Plaka alanlarını doldurun.")
                        
    with sag_panel:
        st.subheader("⚖️ Mevzuat Sohbeti")
        
        if "mesajlar" not in st.session_state:
            st.session_state.mesajlar = []

        for mesaj in st.session_state.mesajlar:
            with st.chat_message(mesaj["rol"]):
                st.markdown(mesaj["icerik"])

        if soru := st.chat_input("Mevzuat hakkında sor..."):
            st.session_state.mesajlar.append({"rol": "user", "icerik": soru})
            with st.chat_message("user"): st.markdown(soru)

            with st.chat_message("assistant"):
                with st.spinner("Taranıyor..."):
                    soru_vektoru = metni_vektore_cevir(soru)
                    skorlar = sorted([(benzerlik_hesapla(soru_vektoru, i["vektor"]), i["metin"]) for i in db], reverse=True)
                    baglam = "\n---\n".join([metin for skor, metin in skorlar[:5]])
                    
                    prompt = f"Sen Grimset Studio uzmanısın. Aşağıdaki bağlama göre cevapla:\nBağlam:\n{baglam}\nSoru: {soru}"
                    response = client.models.generate_content(model=TEXT_MODEL, contents=prompt)
                    
                    st.markdown(response.text)
                    st.session_state.mesajlar.append({"rol": "assistant", "icerik": response.text})

        if st.session_state.mesajlar:
            sohbet_metni = "\n".join([f"{m['rol'].upper()}: {m['icerik']}\n" for m in st.session_state.mesajlar])
            st.download_button("Dosyayı İndir", data=sohbet_metni, file_name="sohbet.txt", use_container_width=True)

elif sayfa == "Teklif Karşılaştırma":
    # --- TEKLİF KARŞILAŞTIRMA MODÜLÜ ---
    st.title("⚖️ Teklif Karşılaştırma Analizi")
    st.markdown("İki farklı sigorta teklifini yükleyerek satış kapatma argümanlarını otomatik oluşturun.")
    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        teklif_1 = st.file_uploader("1. Teklif (A Şirketi)", type=["jpg", "png"], key="t1")
        if teklif_1: st.image(teklif_1, use_container_width=True)
    with col2:
        teklif_2 = st.file_uploader("2. Teklif (B Şirketi)", type=["jpg", "png"], key="t2")
        if teklif_2: st.image(teklif_2, use_container_width=True)

    if teklif_1 and teklif_2:
        if st.button("Teklifleri Kıyasla", use_container_width=True):
            with st.spinner("Analiz ediliyor..."):
                st.markdown(teklif_karsilastir(teklif_1, teklif_2))

elif sayfa == "Yönetici Paneli (Alarm)":
    # --- YÖNETİCİ PANELİ VE VADE TAKVİMİ ---
    st.title("🔒 Yönetici Paneli")
    st.write("Müşteri veri tabanı ve poliçe yenileme takvimi.")
    st.markdown("---")

    sifre = st.text_input("Giriş Şifreniz:", type="password")

    if sifre == "Grimset2026":
        st.success("Giriş Başarılı!")
        
        conn = sqlite3.connect('grimset_crm.db')
        c = conn.cursor()
        
        st.subheader("⏳ Yaklaşan Poliçe Yenilemeleri")
        bugun = datetime.now().date().isoformat()
        
        # Tarihi yaklaşanları veya geçenleri en üste getirecek şekilde sıralıyoruz
        c.execute("SELECT musteri_adi, telefon, plaka, vade_tarihi, ocr_verisi FROM musteri_portfoyu ORDER BY vade_tarihi ASC")
        kayitlar = c.fetchall()
        conn.close()

        if kayitlar:
            for kayit in kayitlar:
                musteri_adi, telefon, plaka, vade_tarihi, ocr_verisi = kayit
                
                # Tarih hesaplaması (yaklaşanları renklendirmek için)
                vade_tarih_obj = datetime.strptime(vade_tarihi, "%Y-%m-%d").date()
                kalan_gun = (vade_tarih_obj - datetime.now().date()).days
                
                durum_ikonu = "🔴" if kalan_gun <= 0 else ("🟡" if kalan_gun <= 15 else "🟢")
                
                with st.expander(f"{durum_ikonu} {vade_tarihi} | {musteri_adi} - Plaka: {plaka} | Kalan Gün: {kalan_gun}"):
                    st.write(f"**Telefon:** {telefon}")
                    st.text(f"Ayıklanan Kayıt Detayı:\n{ocr_verisi}")
        else:
            st.info("Sistemde henüz kaydedilmiş bir müşteri/vade verisi bulunmuyor.")
            
    elif sifre:
        st.error("Hatalı şifre!")
