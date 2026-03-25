import os
import math
import pickle
import sqlite3
from datetime import datetime
import streamlit as st
from pypdf import PdfReader
from google import genai
from PIL import Image
from fpdf import FPDF # YENİ EKLENEN KÜTÜPHANE

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

# --- 1. AŞAMA: GELİŞMİŞ CRM VE POLİÇE VERİTABANI ---
def veritabani_kur():
    conn = sqlite3.connect('grimset_crm.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS ruhsat_kayitlari (id INTEGER PRIMARY KEY AUTOINCREMENT, tarih TEXT, ayiklanan_veri TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS musteri_portfoyu (id INTEGER PRIMARY KEY AUTOINCREMENT, musteri_adi TEXT, telefon TEXT, plaka TEXT, vade_tarihi DATE, eklenme_tarihi TEXT, ocr_verisi TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS uretilen_policeler (id INTEGER PRIMARY KEY AUTOINCREMENT, musteri_adi TEXT, plaka TEXT, police_tipi TEXT, teminatlar TEXT, toplam_prim TEXT, olusturulma_tarihi TEXT)''')
    conn.commit()
    conn.close()

veritabani_kur()

# --- Arka Plan Fonksiyonları (Vektör & OCR) ---
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
        with st.spinner("PDF'ler taranıyor..."):
            return hafizayi_olustur_ve_kaydet()

def ruhsat_oku(gorsel_dosya):
    gorsel = Image.open(gorsel_dosya)
    prompt = """Sen analitik bir OCR asistanısın. Gönderilen fotoğrafı analiz et. SADECE alanları ayıkla ve temiz liste ver."""
    try:
        response = client.models.generate_content(model=VISION_MODEL, contents=[prompt, gorsel])
        return response.text
    except Exception as e:
        return None

def teklif_karsilastir(gorsel_1, gorsel_2):
    img1 = Image.open(gorsel_1)
    img2 = Image.open(gorsel_2)
    prompt = """Sen Grimset Studio'nun yetenekli sigorta satış uzmanısın. İki teklifi kıyasla ve raporla."""
    try:
        response = client.models.generate_content(model=VISION_MODEL, contents=[prompt, img1, img2])
        return response.text
    except Exception as e:
        return None

# --- YENİ: PDF ÜRETME FONKSİYONU ---
def pdf_olustur(musteri, plaka, tip, teminatlar, prim):
    pdf = FPDF()
    pdf.add_page()
    
    # Türkçe karakterleri PDF için basit formata çeviriyoruz
    tr_map = str.maketrans("ğüşöçıİĞÜŞÖÇ", "gusociIGUSOC")
    
    # Başlık
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "GRIMSET STUDIO - POLICE TEKLIFI", ln=True, align="C")
    pdf.ln(10)
    
    # İçerik
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Musteri Ad/Soyad: {musteri.translate(tr_map)}", ln=True)
    pdf.cell(0, 10, f"Arac Plakasi: {plaka.translate(tr_map)}", ln=True)
    pdf.cell(0, 10, f"Police Tipi: {tip.translate(tr_map)}", ln=True)
    pdf.ln(5)
    
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Secili Teminatlar ve Kapsam:", ln=True)
    pdf.set_font("Arial", "", 12)
    pdf.multi_cell(0, 10, teminatlar.translate(tr_map))
    pdf.ln(10)
    
    # Fiyat
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"Hesaplanan Toplam Prim: {prim}", ln=True)
    
    pdf.ln(20)
    pdf.set_font("Arial", "I", 10)
    pdf.cell(0, 10, "Bu belge Grimset Studio Sigorta Otomasyonu tarafindan uretilmistir.", ln=True, align="C")
    
    return pdf.output(dest="S").encode("latin-1")

db = veritabani_yukle()

# --- YAN MENÜ ---
st.sidebar.image("https://images.squarespace-cdn.com/content/v1/6055d01a61b2383be553b1b6/bd6d8e20-94d0-4e36-b552-6d2c4b574229/grimset+copy+copy+logo.png?format=1500w", width=150)
st.sidebar.title("Sistem Modülleri")
sayfa = st.sidebar.radio("Modül Seçimi:", [
    "Ana Sayfa (Müşteri Kayıt)", 
    "📝 Poliçe Atölyesi (Üretim)", 
    "Teklif Karşılaştırma", 
    "Yönetici Paneli (Alarm)"
])
st.sidebar.markdown("---")
st.sidebar.caption("Grimset Studio © 2026")

if sayfa == "Ana Sayfa (Müşteri Kayıt)":
    # (Ana Sayfa kodları aynı kalıyor - Yer tasarrufu için önceki yapı korundu)
    sol_panel, sag_panel = st.columns([1, 2], gap="large")
    with sol_panel:
        st.title("🏢 Sigorta Otomasyonu")
        st.markdown("---")
        st.subheader("📄 Ruhsat Ayıklama ve Kayıt")
        if "son_ocr" not in st.session_state: st.session_state.son_ocr = None
        yuklenen_gorsel = st.file_uploader("Ruhsat fotoğrafı yükle...", type=["jpg", "jpeg", "png"])
        if yuklenen_gorsel:
            st.image(yuklenen_gorsel, use_container_width=True)
            if st.button("Belgeden Verileri Ayıkla", use_container_width=True):
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
                m_vade = st.date_input("Vade")
                if st.form_submit_button("Sisteme Kaydet"):
                    if m_adi and m_plaka:
                        conn = sqlite3.connect('grimset_crm.db')
                        c = conn.cursor()
                        c.execute("INSERT INTO musteri_portfoyu (musteri_adi, telefon, plaka, vade_tarihi, eklenme_tarihi, ocr_verisi) VALUES (?, ?, ?, ?, ?, ?)", (m_adi, m_tel, m_plaka, m_vade, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state.son_ocr))
                        conn.commit()
                        conn.close()
                        st.success("Kaydedildi!")
                        st.session_state.son_ocr = None
                    else: st.warning("Ad ve Plaka zorunlu.")
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

elif sayfa == "📝 Poliçe Atölyesi (Üretim)":
    st.title("📝 Poliçe Atölyesi (Üretim & Düzenleme)")
    st.markdown("---")

    col1, col2 = st.columns([1, 1], gap="large")
    
    with col1:
        st.subheader("1. Müşteri & Araç Bilgileri")
        p_musteri = st.text_input("Müşteri Adı Soyadı", placeholder="Örn: Ahmet Yılmaz")
        p_plaka = st.text_input("Araç Plakası", placeholder="Örn: 34 GRM 26")
        p_tip = st.selectbox("Poliçe Tipi", ["Genişletilmiş Kasko", "Dar Kasko", "Zorunlu Trafik Sigortası", "DASK"])
        
        st.subheader("2. Teminat Seçimleri")
        teminat_cam = st.checkbox("Sınırsız Orijinal Cam Değişimi", value=True)
        teminat_ikame = st.selectbox("İkame Araç Süresi", ["Yılda 2 Kez, 15 Gün", "Yılda 2 Kez, 7 Gün", "İkame Araç Yok"])
        teminat_imm = st.select_slider("İhtiyari Mali Mesuliyet (İMM) Limiti", options=["1.000.000 TL", "5.000.000 TL", "10.000.000 TL", "Sınırsız"], value="10.000.000 TL")
        teminat_yurtdisi = st.checkbox("Yurtdışı Teminatı (Opsiyonel)")
        
    with col2:
        st.subheader("3. Prim & Taslak Özeti")
        tahmini_prim = 15000
        if p_tip == "Genişletilmiş Kasko": tahmini_prim += 5000
        if teminat_cam: tahmini_prim += 1200
        if teminat_imm == "Sınırsız": tahmini_prim += 3000
        if teminat_yurtdisi: tahmini_prim += 2500
        
        prim_yazisi = f"{tahmini_prim:,} TL"
        st.info(f"**Hesaplanan Tahmini Prim:** {prim_yazisi}")
        
        teminat_ozeti = f"- Cam: {'Orijinal (Sinirsiz)' if teminat_cam else 'Muafiyetli'}\n- Ikame Arac: {teminat_ikame}\n- IMM Limiti: {teminat_imm}\n- Yurtdisi: {'Var' if teminat_yurtdisi else 'Yok'}"
        
        st.text(f"Müşteri: {p_musteri}\nPlaka: {p_plaka}\nÜrün: {p_tip}\n\nTeminatlar:\n{teminat_ozeti}")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💾 Sisteme Kaydet", type="primary", use_container_width=True):
                if p_musteri and p_plaka:
                    conn = sqlite3.connect('grimset_crm.db')
                    c = conn.cursor()
                    c.execute("INSERT INTO uretilen_policeler (musteri_adi, plaka, police_tipi, teminatlar, toplam_prim, olusturulma_tarihi) VALUES (?, ?, ?, ?, ?, ?)", (p_musteri, p_plaka, p_tip, teminat_ozeti, prim_yazisi, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                    conn.commit()
                    conn.close()
                    st.success("Kaydedildi!")
                else: st.error("Eksik bilgi!")
        
        with col_btn2:
            # YENİ EKLENEN PDF İNDİRME BUTONU
            if p_musteri and p_plaka:
                pdf_dosyasi = pdf_olustur(p_musteri, p_plaka, p_tip, teminat_ozeti, prim_yazisi)
                st.download_button(
                    label="📄 PDF Olarak İndir",
                    data=pdf_dosyasi,
                    file_name=f"Grimset_Teklif_{p_plaka}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            else:
                st.button("📄 PDF Olarak İndir (Bilgileri Girin)", disabled=True, use_container_width=True)

elif sayfa == "Teklif Karşılaştırma":
    # (Mevcut Karşılaştırma kodları)
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
    # (Mevcut Yönetici Paneli)
    st.title("🔒 Yönetici Paneli")
    sifre = st.text_input("Şifreniz:", type="password")
    if sifre == "Grimset2026":
        conn = sqlite3.connect('grimset_crm.db')
        c = conn.cursor()
        st.subheader("⏳ Yenilemeler")
        c.execute("SELECT musteri_adi, plaka, vade_tarihi FROM musteri_portfoyu ORDER BY vade_tarihi ASC")
        for k in c.fetchall():
            st.write(f"{k[2]} | {k[0]} - {k[1]}")
        conn.close()
