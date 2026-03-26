import os
import math
import pickle
import json
import urllib.parse
import streamlit as st
import pandas as pd # Veri analizi için eklendi
import plotly.express as px # İnteraktif grafikler için eklendi
from datetime import datetime
from pypdf import PdfReader
from google import genai
from PIL import Image
from fpdf import FPDF
import gspread
from google.oauth2.service_account import Credentials

# --- Sayfa Ayarları ---
st.set_page_config(page_title="Grimset AI | Sigorta Otomasyonu", page_icon="🛡️", layout="wide")

# --- ÖZEL UI/UX CSS GİYDİRMESİ (PREMIUM GÖRÜNÜM) ---
st.markdown("""
<style>
    /* Buton Tasarımları */
    .stButton>button {
        border-radius: 8px;
        transition: all 0.3s ease-in-out;
        font-weight: bold;
    }
    .stButton>button:hover {
        transform: scale(1.02);
        box-shadow: 0px 4px 15px rgba(0,0,0,0.1);
    }
    /* Veri Kartları (Metrikler) Tasarımı */
    div[data-testid="metric-container"] {
        background-color: #1e1e1e;
        border: 1px solid #333;
        padding: 5% 5% 5% 10%;
        border-radius: 10px;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.2);
        color: white;
    }
    /* Sol Menü Arka Planı */
    [data-testid="stSidebar"] {
        background-color: #0e1117;
        border-right: 1px solid #2d2d2d;
    }
</style>
""", unsafe_allow_html=True)

# --- API VE GÜVENLİK AYARLARI ---
api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
if not api_key:
    st.error("Lütfen Gemini API anahtarını ekleyin!")
    st.stop()

client = genai.Client(api_key=api_key)
VISION_MODEL = 'gemini-2.5-flash'
TEXT_MODEL = 'gemini-2.5-flash'

HAFIZA_DOSYASI = "vektor_hafizasi.pkl"
BELGELER_KLASORU = "belgeler"

# --- GOOGLE SHEETS (CANLI CRM) BAĞLANTISI ---
@st.cache_resource
def sheets_baglantisi_kur():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        raw_data = st.secrets["google_json"]
        skey = json.loads(raw_data, strict=False)
        if "\\n" in skey.get("private_key", ""):
            skey["private_key"] = skey["private_key"].replace("\\n", "\n")
            
        credentials = Credentials.from_service_account_info(skey, scopes=scopes)
        gc = gspread.authorize(credentials)
        sh = gc.open("Grimset_CRM")
        
        try:
            ws_musteri = sh.worksheet("Müşteri Portföyü")
        except:
            ws_musteri = sh.add_worksheet(title="Müşteri Portföyü", rows="1000", cols="20")
            ws_musteri.append_row(["Tarih", "Müşteri Adı", "Telefon", "Plaka", "Vade Tarihi", "OCR Detayı"])

        try:
            ws_police = sh.worksheet("Üretilen Poliçeler")
        except:
            ws_police = sh.add_worksheet(title="Üretilen Poliçeler", rows="1000", cols="20")
            ws_police.append_row(["Tarih", "Müşteri Adı", "Plaka", "Poliçe Tipi", "Teminatlar", "Toplam Prim"])
            
        return sh
    except Exception as e:
        st.error(f"Google Sheets Bağlantı Hatası. Detay: {e}")
        return None

sh = sheets_baglantisi_kur()

# --- Arka Plan Fonksiyonları ---
def metni_vektore_cevir(metin):
    response = client.models.embed_content(model='gemini-embedding-001', contents=metin)
    return response.embeddings[0].values

def benzerlik_hesapla(v1, v2):
    dot_product = sum(a * b for a, b in zip(v1, v2))
    magnitude1 = math.sqrt(sum(a * a for a in v1))
    magnitude2 = math.sqrt(sum(a * a for a in v2))
    if magnitude1 * magnitude2 == 0: return 0
    return dot_product / (magnitude1 * magnitude2)

def hafizayi_olustur_ve_kaydet():
    if not os.path.exists(BELGELER_KLASORU): os.makedirs(BELGELER_KLASORU); st.stop()
    pdf_dosyalari = [f for f in os.listdir(BELGELER_KLASORU) if f.endswith('.pdf')]
    if not pdf_dosyalari: return []
    tam_metin = ""
    for dosya in pdf_dosyalari:
        reader = PdfReader(os.path.join(BELGELER_KLASORU, dosya))
        for sayfa in reader.pages:
            if sayfa.extract_text(): tam_metin += f"\n[Kaynak: {dosya}]\n" + sayfa.extract_text() + "\n"
    parcalar = [tam_metin[i:i+1000] for i in range(0, len(tam_metin), 1000)]
    veritabani = [{"metin": p, "vektor": metni_vektore_cevir(p)} for p in parcalar if len(p.strip()) > 50]
    with open(HAFIZA_DOSYASI, 'wb') as f: pickle.dump(veritabani, f)
    return veritabani

@st.cache_resource
def veritabani_yukle():
    if os.path.exists(HAFIZA_DOSYASI):
        with open(HAFIZA_DOSYASI, 'rb') as f: return pickle.load(f)
    return hafizayi_olustur_ve_kaydet()

def ruhsat_oku(gorsel_dosya):
    try: return client.models.generate_content(model=VISION_MODEL, contents=["SADECE alanları ayıkla ve temiz liste ver.", Image.open(gorsel_dosya)]).text
    except: return None

def teklif_karsilastir(gorsel_1, gorsel_2):
    try: return client.models.generate_content(model=VISION_MODEL, contents=["İki teklifi kıyasla ve raporla.", Image.open(gorsel_1), Image.open(gorsel_2)]).text
    except: return None

def pdf_olustur(musteri, plaka, tip, teminatlar, prim):
    pdf = FPDF()
    pdf.add_page()
    tr_map = str.maketrans("ğüşöçıİĞÜŞÖÇ", "gusociIGUSOC")
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "GRIMSET STUDIO - POLICE TEKLIFI", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Musteri: {musteri.translate(tr_map)}", ln=True)
    pdf.cell(0, 10, f"Arac Plakasi: {plaka.translate(tr_map)}", ln=True)
    pdf.cell(0, 10, f"Police Tipi: {tip.translate(tr_map)}", ln=True)
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Secili Teminatlar:", ln=True)
    pdf.multi_cell(0, 10, teminatlar.translate(tr_map))
    pdf.ln(10)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"Toplam Prim: {prim}", ln=True)
    return pdf.output(dest="S").encode("latin-1")

db = veritabani_yukle()

# --- YAN MENÜ ---
st.sidebar.image("https://images.squarespace-cdn.com/content/v1/6055d01a61b2383be553b1b6/bd6d8e20-94d0-4e36-b552-6d2c4b574229/grimset+copy+copy+logo.png?format=1500w", width=150)
st.sidebar.title("Modüller")
sayfa = st.sidebar.radio("İşlem Seçin:", ["📋 Kayıt & Ayıklama", "📝 Poliçe Atölyesi", "⚖️ Karşılaştırma", "📊 Finansal Dashboard"])
st.sidebar.markdown("---")
st.sidebar.caption("Grimset Studio © 2026")

if sayfa == "📋 Kayıt & Ayıklama":
    sol_panel, sag_panel = st.columns([1, 2], gap="large")
    with sol_panel:
        st.title("🛡️ Evrak Okuma")
        st.markdown("---")
        if "son_ocr" not in st.session_state: st.session_state.son_ocr = None
        yuklenen_gorsel = st.file_uploader("Ruhsat veya Kimlik yükle...", type=["jpg", "jpeg", "png"])
        if yuklenen_gorsel:
            st.image(yuklenen_gorsel, use_container_width=True)
            if st.button("Verileri Ayıkla", use_container_width=True):
                with st.spinner("Gemini Vision çalışıyor..."):
                    ayiklanan = ruhsat_oku(yuklenen_gorsel)
                    if ayiklanan:
                        st.session_state.son_ocr = ayiklanan
                        st.success("Başarılı!")
        if st.session_state.son_ocr:
            st.text_area("Bilgiler", value=st.session_state.son_ocr, height=200)
            with st.form("crm_form"):
                m_adi = st.text_input("Ad Soyad")
                m_tel = st.text_input("Telefon")
                m_plaka = st.text_input("Plaka")
                m_vade = st.date_input("Vade Tarihi")
                if st.form_submit_button("Google Sheets'e Kaydet"):
                    if m_adi and m_plaka and sh:
                        try:
                            zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            sh.worksheet("Müşteri Portföyü").append_row([zaman, m_adi, m_tel, m_plaka, str(m_vade), st.session_state.son_ocr])
                            st.success("Veriler anında Google Sheets'e işlendi!")
                            st.session_state.son_ocr = None
                        except Exception as e: st.error(f"Hata: {e}")
                    else: st.warning("Eksik bilgi veya bağlantı yok.")
    with sag_panel:
        st.subheader("🤖 Mevzuat Sohbeti")
        if "mesajlar" not in st.session_state: st.session_state.mesajlar = []
        for mesaj in st.session_state.mesajlar:
            with st.chat_message(mesaj["rol"]): st.markdown(mesaj["icerik"])
        if soru := st.chat_input("Sorunuz..."):
            st.session_state.mesajlar.append({"rol": "user", "icerik": soru})
            with st.chat_message("user"): st.markdown(soru)
            with st.chat_message("assistant"):
                with st.spinner("Taranıyor..."):
                    soru_vektoru = metni_vektore_cevir(soru)
                    skorlar = sorted([(benzerlik_hesapla(soru_vektoru, i["vektor"]), i["metin"]) for i in db], reverse=True)
                    baglam = "\n---\n".join([m for s, m in skorlar[:5]])
                    response = client.models.generate_content(model=TEXT_MODEL, contents=f"Bağlama göre cevapla:\n{baglam}\nSoru: {soru}")
                    st.markdown(response.text)
                    st.session_state.mesajlar.append({"rol": "assistant", "icerik": response.text})

elif sayfa == "📝 Poliçe Atölyesi":
    st.title("📝 Poliçe Atölyesi (Üretim)")
    st.markdown("---")
    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        p_musteri = st.text_input("Müşteri Adı Soyadı")
        p_tel = st.text_input("Telefon (5XX... Whatsapp için)")
        p_plaka = st.text_input("Araç Plakası")
        p_tip = st.selectbox("Poliçe Tipi", ["Kasko", "Zorunlu Trafik Sigortası", "DASK"])
        teminat_cam = st.checkbox("Sınırsız Orijinal Cam Değişimi", value=True)
        teminat_ikame = st.selectbox("İkame Araç Süresi", ["Yılda 2 Kez, 15 Gün", "Yılda 2 Kez, 7 Gün", "İkame Araç Yok"])
        teminat_imm = st.select_slider("İMM Limiti", options=["1.000.000 TL", "5.000.000 TL", "Sınırsız"], value="5.000.000 TL")
    with col2:
        tahmini_prim = 15000 + (5000 if p_tip=="Kasko" else 0) + (1200 if teminat_cam else 0) + (3000 if teminat_imm=="Sınırsız" else 0)
        prim_yazisi = f"{tahmini_prim:,} TL"
        st.info(f"**Tahmini Prim:** {prim_yazisi}")
        teminat_ozeti = f"- Cam: {'Sınırsız' if teminat_cam else 'Muafiyetli'}\n- İkame: {teminat_ikame}\n- İMM: {teminat_imm}"
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💾 Google Sheets'e Kaydet", use_container_width=True):
                if p_musteri and p_plaka and sh:
                    try:
                        sh.worksheet("Üretilen Poliçeler").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), p_musteri, p_plaka, p_tip, teminat_ozeti, prim_yazisi])
                        st.success("Kaydedildi!")
                    except Exception as e: st.error(f"Hata: {e}")
        with col_btn2:
            if p_musteri and p_plaka:
                st.download_button("📄 PDF İndir", data=pdf_olustur(p_musteri, p_plaka, p_tip, teminat_ozeti, prim_yazisi), file_name=f"Teklif_{p_plaka}.pdf", mime="application/pdf", use_container_width=True)
        
        if p_musteri and p_plaka:
            st.markdown("---")
            wp_mesaj = urllib.parse.quote(f"Merhaba {p_musteri},\nGrimset Studio güvencesiyle {p_plaka} plakalı aracınız için {p_tip} teklifiniz hazırlanmıştır.\n\n*Tutar:* {prim_yazisi}")
            wa_link = f"https://wa.me/90{p_tel.replace(' ', '').replace('+90', '').replace('0', '', 1)}?text={wp_mesaj}" if p_tel else f"https://wa.me/?text={wp_mesaj}"
            st.markdown(f'<a href="{wa_link}" target="_blank" style="text-decoration: none;"><div style="background-color: #25D366; color: white; text-align: center; padding: 10px; border-radius: 8px; font-weight: bold;">💬 WhatsApp\'tan Gönder</div></a>', unsafe_allow_html=True)

elif sayfa == "⚖️ Karşılaştırma":
    st.title("⚖️ Teklif Karşılaştırma Analizi")
    col1, col2 = st.columns(2)
    with col1:
        t1 = st.file_uploader("1. Teklif", type=["jpg", "png"], key="t1")
        if t1: st.image(t1)
    with col2:
        t2 = st.file_uploader("2. Teklif", type=["jpg", "png"], key="t2")
        if t2: st.image(t2)
    if t1 and t2:
        if st.button("Kıyasla"): st.markdown(teklif_karsilastir(t1, t2))

elif sayfa == "📊 Finansal Dashboard":
    st.title("📊 Yönetici Finansal Dashboard")
    st.markdown("---")
    
    if sh:
        try:
            policeler = sh.worksheet("Üretilen Poliçeler").get_all_records()
            if not policeler:
                st.info("Henüz üretilmiş poliçe verisi bulunmuyor.")
                st.stop()
                
            # Veriyi Pandas DataFrame'e çevir ve temizle
            df = pd.DataFrame(policeler)
            df['Saf Prim'] = df['Toplam Prim'].astype(str).str.replace(' TL', '').str.replace(',', '').astype(float)
            toplam_ciro = df['Saf Prim'].sum()
            
            # KPI Kartları
            col1, col2, col3 = st.columns(3)
            col1.metric("💼 Toplam Kesilen Poliçe", f"{len(df)} Adet")
            col2.metric("📈 Toplam Üretim (Ciro)", f"{int(toplam_ciro):,} TL")
            col3.metric("🏆 En Çok Satılan", str(df['Poliçe Tipi'].mode()[0]))
            
            st.markdown("---")
            
            # İnteraktif Grafikler
            g_col1, g_col2 = st.columns(2)
            
            with g_col1:
                st.subheader("Ürünlere Göre Ciro Dağılımı")
                fig_pie = px.pie(df, names='Poliçe Tipi', values='Saf Prim', hole=0.4, color_discrete_sequence=px.colors.sequential.Teal)
                st.plotly_chart(fig_pie, use_container_width=True)
                
            with g_col2:
                st.subheader("Poliçe Kesim Grafiği")
                df['Kısa Tarih'] = pd.to_datetime(df['Tarih']).dt.date
                gunluk_df = df.groupby('Kısa Tarih')['Saf Prim'].sum().reset_index()
                fig_bar = px.bar(gunluk_df, x='Kısa Tarih', y='Saf Prim', text_auto='.2s', color_discrete_sequence=['#4CAF50'])
                st.plotly_chart(fig_bar, use_container_width=True)
                
            st.markdown("---")
            st.subheader("Son İşlemler Geçmişi")
            st.dataframe(df[['Tarih', 'Müşteri Adı', 'Plaka', 'Poliçe Tipi', 'Toplam Prim']].tail(10).iloc[::-1], use_container_width=True)
            
        except Exception as e:
            st.warning(f"Dashboard yüklenirken hata oluştu: {e}. Lütfen Excel tablonuzun doğruluğunu kontrol edin.")
