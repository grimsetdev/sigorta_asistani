import os
import math
import pickle
import streamlit as st
from datetime import datetime
from pypdf import PdfReader
from google import genai
from PIL import Image
from fpdf import FPDF
import gspread
from google.oauth2.service_account import Credentials

# --- Sayfa Ayarları ---
st.set_page_config(page_title="Grimset AI | Sigorta Otomasyonu", page_icon="🏢", layout="wide")

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

# --- 1. AŞAMA: GOOGLE SHEETS (CANLI CRM) BAĞLANTISI ---
@st.cache_resource
def sheets_baglantisi_kur():
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        skey = dict(st.secrets["gcp_service_account"])
        
        # KRİTİK DÜZELTME: TOML'dan gelen bozuk satır atlamalarını (\n) gerçek alt satıra çevir
        if "\\n" in skey["private_key"]:
            skey["private_key"] = skey["private_key"].replace("\\n", "\n")
            
        credentials = Credentials.from_service_account_info(skey, scopes=scopes)
        gc = gspread.authorize(credentials)
        
        # Grimset_CRM adlı excel dosyasını bulur
        sh = gc.open("Grimset_CRM")
        
        # Sekmeler yoksa oluşturur
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
        st.error(f"Google Sheets Bağlantı Hatası: Lütfen Secrets ayarlarını kontrol edin. Detay: {e}")
        return None

sh = sheets_baglantisi_kur()

# --- Arka Plan Fonksiyonları (Vektör, OCR, PDF) ---
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
    if not os.path.exists(BELGELER_KLASORU):
        os.makedirs(BELGELER_KLASORU)
        st.stop()
    pdf_dosyalari = [f for f in os.listdir(BELGELER_KLASORU) if f.endswith('.pdf')]
    if not pdf_dosyalari: return []
    tam_metin = ""
    for dosya in pdf_dosyalari:
        reader = PdfReader(os.path.join(BELGELER_KLASORU, dosya))
        for sayfa in reader.pages:
            if sayfa.extract_text():
                tam_metin += f"\n[Kaynak: {dosya}]\n" + sayfa.extract_text() + "\n"
    parcalar = [tam_metin[i:i+1000] for i in range(0, len(tam_metin), 1000)]
    veritabani = []
    for parca in parcalar:
        if len(parca.strip()) > 50: 
            veritabani.append({"metin": parca, "vektor": metni_vektore_cevir(parca)})
    with open(HAFIZA_DOSYASI, 'wb') as f:
        pickle.dump(veritabani, f)
    return veritabani

@st.cache_resource
def veritabani_yukle():
    if os.path.exists(HAFIZA_DOSYASI):
        with open(HAFIZA_DOSYASI, 'rb') as f:
            return pickle.load(f)
    return hafizayi_olustur_ve_kaydet()

def ruhsat_oku(gorsel_dosya):
    prompt = "Sen analitik bir OCR asistanısın. Gönderilen fotoğrafı analiz et. SADECE alanları ayıkla ve temiz liste ver."
    try:
        return client.models.generate_content(model=VISION_MODEL, contents=[prompt, Image.open(gorsel_dosya)]).text
    except: return None

def teklif_karsilastir(gorsel_1, gorsel_2):
    prompt = "Sen Grimset Studio'nun yetenekli sigorta satış uzmanısın. İki teklifi kıyasla ve raporla."
    try:
        return client.models.generate_content(model=VISION_MODEL, contents=[prompt, Image.open(gorsel_1), Image.open(gorsel_2)]).text
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
    pdf.set_font("Arial", "", 12)
    pdf.multi_cell(0, 10, teminatlar.translate(tr_map))
    pdf.ln(10)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"Toplam Prim: {prim}", ln=True)
    return pdf.output(dest="S").encode("latin-1")

db = veritabani_yukle()

# --- YAN MENÜ ---
st.sidebar.image("https://images.squarespace-cdn.com/content/v1/6055d01a61b2383be553b1b6/bd6d8e20-94d0-4e36-b552-6d2c4b574229/grimset+copy+copy+logo.png?format=1500w", width=150)
st.sidebar.title("Sistem Modülleri")
sayfa = st.sidebar.radio("Modül Seçimi:", ["Ana Sayfa (Müşteri Kayıt)", "📝 Poliçe Atölyesi", "Teklif Karşılaştırma", "Yönetici Paneli (Alarm)"])
st.sidebar.markdown("---")
st.sidebar.caption("Grimset Studio © 2026")

if sayfa == "Ana Sayfa (Müşteri Kayıt)":
    sol_panel, sag_panel = st.columns([1, 2], gap="large")
    with sol_panel:
        st.title("🏢 Sigorta Otomasyonu")
        st.markdown("---")
        if "son_ocr" not in st.session_state: st.session_state.son_ocr = None
        yuklenen_gorsel = st.file_uploader("Ruhsat fotoğrafı yükle...", type=["jpg", "jpeg", "png"])
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
                            ws = sh.worksheet("Müşteri Portföyü")
                            ws.append_row([zaman, m_adi, m_tel, m_plaka, str(m_vade), st.session_state.son_ocr])
                            st.success("Veriler anında Google Sheets'e işlendi!")
                            st.session_state.son_ocr = None
                        except Exception as e:
                            st.error(f"Kayıt Hatası: {e}")
                    else: st.warning("Ad ve Plaka zorunlu veya Sheets bağlantısı kurulamadı.")
    with sag_panel:
        st.subheader("⚖️ Mevzuat Sohbeti")
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
                    baglam = "\n---\n".join([metin for skor, metin in skorlar[:5]])
                    response = client.models.generate_content(model=TEXT_MODEL, contents=f"Bağlama göre cevapla:\n{baglam}\nSoru: {soru}")
                    st.markdown(response.text)
                    st.session_state.mesajlar.append({"rol": "assistant", "icerik": response.text})

elif sayfa == "📝 Poliçe Atölyesi":
    st.title("📝 Poliçe Atölyesi (Üretim)")
    st.markdown("---")
    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        p_musteri = st.text_input("Müşteri Adı Soyadı")
        p_plaka = st.text_input("Araç Plakası")
        p_tip = st.selectbox("Poliçe Tipi", ["Kasko", "Zorunlu Trafik Sigortası", "DASK"])
        teminat_cam = st.checkbox("Sınırsız Orijinal Cam Değişimi", value=True)
        teminat_ikame = st.selectbox("İkame Araç Süresi", ["Yılda 2 Kez, 15 Gün", "Yılda 2 Kez, 7 Gün", "İkame Araç Yok"])
        teminat_imm = st.select_slider("İMM Limiti", options=["1.000.000 TL", "5.000.000 TL", "Sınırsız"], value="5.000.000 TL")
    with col2:
        tahmini_prim = 15000 + (5000 if p_tip=="Kasko" else 0) + (1200 if teminat_cam else 0) + (3000 if teminat_imm=="Sınırsız" else 0)
        prim_yazisi = f"{tahmini_prim:,} TL"
        st.info(f"**Tahmini Prim:** {prim_yazisi}")
        teminat_ozeti = f"- Cam: {'Sinirsiz' if teminat_cam else 'Muafiyetli'}\n- Ikame: {teminat_ikame}\n- IMM: {teminat_imm}"
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💾 Google Sheets'e Kaydet", type="primary", use_container_width=True):
                if p_musteri and p_plaka and sh:
                    try:
                        ws = sh.worksheet("Üretilen Poliçeler")
                        zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        ws.append_row([zaman, p_musteri, p_plaka, p_tip, teminat_ozeti, prim_yazisi])
                        st.success("Google Sheets'e Kaydedildi!")
                    except Exception as e:
                        st.error(f"Kayıt Hatası: {e}")
        with col_btn2:
            if p_musteri and p_plaka:
                st.download_button(label="📄 PDF İndir", data=pdf_olustur(p_musteri, p_plaka, p_tip, teminat_ozeti, prim_yazisi), file_name=f"Teklif_{p_plaka}.pdf", mime="application/pdf", use_container_width=True)

elif sayfa == "Teklif Karşılaştırma":
    st.title("⚖️ Teklif Karşılaştırma Analizi")
    col1, col2 = st.columns(2)
    with col1:
        t1 = st.file_uploader("1. Teklif", type=["jpg", "png"], key="t1")
        if t1: st.image(t1)
    with col2:
        t2 = st.file_uploader("2. Teklif", type=["jpg", "png"], key="t2")
        if t2: st.image(t2)
    if t1 and t2:
        if st.button("Kıyasla"):
            st.markdown(teklif_karsilastir(t1, t2))

elif sayfa == "Yönetici Paneli (Alarm)":
    st.title("🔒 Yönetici Paneli")
    st.info("Canlı Google Sheets Verileri Çekiliyor...")
    if sh:
        try:
            ws = sh.worksheet("Müşteri Portföyü")
            kayitlar = ws.get_all_records()
            st.subheader(f"Toplam Kayıtlı Müşteri: {len(kayitlar)}")
            for k in kayitlar:
                st.write(f"**{k['Vade Tarihi']}** | {k['Müşteri Adı']} - {k['Plaka']} | Tel: {k['Telefon']}")
        except Exception as e:
            st.error("Henüz kayıt bulunamadı veya sekme okunamadı.")
