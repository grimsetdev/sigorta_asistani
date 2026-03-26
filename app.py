import os
import math
import pickle
import json
import urllib.parse
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from pypdf import PdfReader
from google import genai
from PIL import Image
from fpdf import FPDF
import gspread
from google.oauth2.service_account import Credentials
from streamlit_mic_recorder import speech_to_text
from streamlit_tags import st_tags

# --- Sayfa Ayarları ---
st.set_page_config(page_title="Grimset AI | Sigorta Otomasyonu", page_icon="🛡️", layout="wide")

# --- ÖZEL UI/UX CSS GİYDİRMESİ ---
st.markdown("""
<style>
    .stButton>button { border-radius: 8px; transition: all 0.3s ease-in-out; font-weight: bold; }
    .stButton>button:hover { transform: scale(1.02); box-shadow: 0px 4px 15px rgba(0,0,0,0.1); }
    div[data-testid="metric-container"] { background-color: #1e1e1e; border: 1px solid #333; padding: 5% 5% 5% 10%; border-radius: 10px; box-shadow: 2px 2px 10px rgba(0,0,0,0.2); color: white; }
    [data-testid="stSidebar"] { background-color: #0e1117; border-right: 1px solid #2d2d2d; }
    .login-box { max-width: 400px; margin: auto; padding: 2rem; border-radius: 10px; background-color: #1e1e1e; box-shadow: 0 4px 8px rgba(0,0,0,0.2); }
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

# --- GOOGLE SHEETS BAĞLANTISI ---
@st.cache_resource
def sheets_baglantisi_kur():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        raw_data = st.secrets["google_json"]
        skey = json.loads(raw_data, strict=False)
        if "\\n" in skey.get("private_key", ""): skey["private_key"] = skey["private_key"].replace("\\n", "\n")
        credentials = Credentials.from_service_account_info(skey, scopes=scopes)
        gc = gspread.authorize(credentials)
        sh = gc.open("Grimset_CRM")
        try: ws_musteri = sh.worksheet("Müşteri Portföyü")
        except:
            ws_musteri = sh.add_worksheet(title="Müşteri Portföyü", rows="1000", cols="20")
            ws_musteri.append_row(["Tarih", "Müşteri Adı", "Telefon", "Plaka", "Vade Tarihi", "OCR Detayı"])
        try: ws_police = sh.worksheet("Üretilen Poliçeler")
        except:
            ws_police = sh.add_worksheet(title="Üretilen Poliçeler", rows="1000", cols="20")
            ws_police.append_row(["Tarih", "Müşteri Adı", "Plaka", "Poliçe Tipi", "Teminatlar", "Toplam Prim", "Satış Temsilcisi", "Net Komisyon"])
        try: ws_hasar = sh.worksheet("Hasar Kayıtları")
        except:
            ws_hasar = sh.add_worksheet(title="Hasar Kayıtları", rows="1000", cols="20")
            ws_hasar.append_row(["Tarih", "Müşteri Adı", "Plaka", "Hasar Raporu"])
        try: ws_filo = sh.worksheet("Filo Teklifleri")
        except:
            ws_filo = sh.add_worksheet(title="Filo Teklifleri", rows="1000", cols="20")
            ws_filo.append_row(["Tarih", "Firma Adı", "Araç Sayısı", "Plakalar", "Poliçe Tipi", "Toplam Prim", "Satış Temsilcisi", "Net Komisyon"])
        # YENİ: Satış Hunisi (Kanban) Sekmesi
        try: ws_huni = sh.worksheet("Satış Hunisi")
        except:
            ws_huni = sh.add_worksheet(title="Satış Hunisi", rows="1000", cols="20")
            ws_huni.append_row(["ID", "Tarih", "Müşteri Adı", "Telefon", "Konu", "Tahmini Tutar", "Aşama", "Sorumlu"])
        return sh
    except Exception as e:
        st.error(f"Google Sheets Bağlantı Hatası: {e}")
        return None

sh = sheets_baglantisi_kur()

# --- OTURUM YÖNETİMİ ---
if "giris_yapildi" not in st.session_state:
    st.session_state.giris_yapildi = False
    st.session_state.rol = None
    st.session_state.kullanici_adi = None
    st.session_state.musteri_plaka = None

if not st.session_state.giris_yapildi:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown('<div class="login-box">', unsafe_allow_html=True)
        st.image("https://images.squarespace-cdn.com/content/v1/6055d01a61b2383be553b1b6/bd6d8e20-94d0-4e36-b552-6d2c4b574229/grimset+copy+copy+logo.png?format=1500w", width=200)
        st.markdown("<h3 style='text-align: center;'>Grimset Studio Sistem Girişi</h3>", unsafe_allow_html=True)
        
        tab_personel, tab_musteri = st.tabs(["🧑‍💼 Personel Girişi", "👤 Müşteri Portalı"])
        
        with tab_personel:
            k_adi = st.text_input("Kullanıcı Adı", key="k_adi")
            sifre = st.text_input("Şifre", type="password", key="sifre")
            if st.button("Giriş Yap", use_container_width=True, type="primary"):
                if k_adi == "admin" and sifre == "Grimset2026":
                    st.session_state.giris_yapildi = True
                    st.session_state.rol = "Admin"
                    st.session_state.kullanici_adi = "Yönetici"
                    st.rerun()
                elif k_adi == "ali" and sifre == "satis123":
                    st.session_state.giris_yapildi = True
                    st.session_state.rol = "Satis"
                    st.session_state.kullanici_adi = "Ali"
                    st.rerun()
                else:
                    st.error("Hatalı kullanıcı adı veya şifre!")
                    
        with tab_musteri:
            st.info("Poliçelerinizi görüntülemek için araç plakanızı ve sisteme kayıtlı telefon numaranızı girin.")
            m_plaka_giris = st.text_input("Araç Plakanız (Boşluksuz)", placeholder="Örn: 34ABC123")
            m_tel_giris = st.text_input("Sisteme Kayıtlı Telefon Numaranız", placeholder="Örn: 5551234567", type="password")
            
            if st.button("Müşteri Paneline Gir", use_container_width=True, type="primary"):
                if sh and m_plaka_giris and m_tel_giris:
                    try:
                        musteriler = sh.worksheet("Müşteri Portföyü").get_all_records()
                        giris_basarili = False
                        plaka_input = m_plaka_giris.replace(" ", "").upper()
                        tel_input = m_tel_giris.replace(" ", "")
                        
                        for m in musteriler:
                            db_plaka = str(m.get("Plaka", "")).replace(" ", "").upper()
                            db_tel = str(m.get("Telefon", "")).replace(" ", "")
                            if db_plaka == plaka_input and db_tel == tel_input:
                                st.session_state.giris_yapildi = True
                                st.session_state.rol = "Musteri"
                                st.session_state.kullanici_adi = str(m.get("Müşteri Adı", "Müşteri"))
                                st.session_state.musteri_plaka = db_plaka
                                giris_basarili = True
                                st.rerun()
                                break
                        if not giris_basarili: st.error("Sistemde bu plaka ve telefon numarasıyla eşleşen bir kayıt bulunamadı.")
                    except Exception as e: st.error(f"Veritabanı kontrol hatası: {e}")
                else: st.warning("Lütfen plaka ve telefon numaranızı eksiksiz girin.")
        st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# --- Arka Plan Fonksiyonları ---
def metni_vektore_cevir(metin): return client.models.embed_content(model='gemini-embedding-001', contents=metin).embeddings[0].values
def benzerlik_hesapla(v1, v2):
    dot_product = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(a * a for a in v2))
    if mag1 * mag2 == 0: return 0
    return dot_product / (mag1 * mag2)

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

def coklu_belge_oku(gorsel_dosyalari):
    prompt = """Sen analitik bir OCR asistanısın. Sana gönderilen tüm belgeleri analiz et. 
SADECE aşağıdaki alanları tek bir temiz liste halinde ver. Okunamayan verileri boş bırak:
- Müşteri Adı Soyadı:
- T.C. Kimlik No:
- Araç Plakası:
- Şasi No (VIN):
- Motor No:
- Marka/Model/Yıl:
- Mevcut Poliçe Bitiş Tarihi (Varsa):"""
    try:
        icerik_listesi = [prompt]
        for dosya in gorsel_dosyalari: icerik_listesi.append(Image.open(dosya))
        return client.models.generate_content(model=VISION_MODEL, contents=icerik_listesi).text
    except Exception as e: return f"Hata: {e}"

def kaza_analizi_yap(gorsel_dosyalari, plaka, isim):
    prompt = f"""Sen Grimset Studio'nun uzman eksperisin. Müşterimiz {isim}'e ait {plaka} plakalı aracın kaza görselleri ektedir. Lütfen raporla:
1. GÖRÜNÜR HASAR ANALİZİ
2. KUSUR TAHMİNİ
3. HASAR BEYAN DİLEKÇESİ (Resmi dille)"""
    try:
        icerik_listesi = [prompt]
        for dosya in gorsel_dosyalari: icerik_listesi.append(Image.open(dosya))
        return client.models.generate_content(model=VISION_MODEL, contents=icerik_listesi).text
    except Exception as e: return f"Analiz Hatası: {e}"

def teklif_karsilastir(gorsel_1, gorsel_2):
    try: return client.models.generate_content(model=VISION_MODEL, contents=["İki teklifi kıyasla ve raporla.", Image.open(gorsel_1), Image.open(gorsel_2)]).text
    except: return None

def pdf_olustur(musteri, plaka, tip, teminatlar, prim, piyasa_fiyati=None, kazanc=None, ref_kodu=None):
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
    pdf.cell(0, 10, f"Grimset Ozel Primi: {prim}", ln=True)
    
    if piyasa_fiyati and kazanc:
        pdf.ln(2)
        pdf.set_font("Arial", "", 11)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 10, f"Piyasa Ortalamasi: {piyasa_fiyati}", ln=True)
        pdf.set_text_color(0, 128, 0)
        pdf.set_font("Arial", "B", 13)
        pdf.cell(0, 10, f"Sizin Kazanciniz: {kazanc}", ln=True)
        pdf.set_text_color(0, 0, 0)
        
    if ref_kodu:
        pdf.ln(15)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, "Size Ozel Kazandiran Paylasim Kodunuz!", ln=True, fill=True)
        pdf.set_font("Arial", "B", 14)
        pdf.set_text_color(255, 69, 0)
        pdf.cell(0, 10, f"KOD: {ref_kodu}", ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "", 10)
        pdf.multi_cell(0, 8, "Bu kodu arkadaslarinizla paylasin. Arkadaslariniz bu kodla aninda %5 indirim kazanirken, siz de bir sonraki police yenilemenizde %10 indirim kazanin!")

    return pdf.output(dest="S").encode("latin-1")

def filo_pdf_olustur(firma, plaka_listesi, tip, prim):
    pdf = FPDF()
    pdf.add_page()
    tr_map = str.maketrans("ğüşöçıİĞÜŞÖÇ", "gusociIGUSOC")
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "GRIMSET STUDIO - B2B KURUMSAL FILO TEKLIFI", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Kurumsal Musteri (Firma): {firma.translate(tr_map)}", ln=True)
    pdf.cell(0, 10, f"Police Tipi: {tip.translate(tr_map)}", ln=True)
    pdf.cell(0, 10, f"Toplam Arac Sayisi: {len(plaka_listesi)} Adet", ln=True)
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Kapsamdaki Arac Plakalari:", ln=True)
    pdf.set_font("Arial", "", 10)
    plaka_metni = ", ".join(plaka_listesi)
    pdf.multi_cell(0, 10, plaka_metni.translate(tr_map))
    pdf.ln(10)
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"Uygulanan Filo Indirimi Sonrasi Toplam Prim: {prim:,} TL", ln=True)
    return pdf.output(dest="S").encode("latin-1")

def eposta_gonder(alici_mail, musteri_adi, plaka, tip, teminatlar, prim, pdf_bytes):
    gonderen_mail = st.secrets.get("SMTP_EMAIL")
    sifre = st.secrets.get("SMTP_PASSWORD")
    if not gonderen_mail or not sifre: return False, "E-Posta ayarları eksik!"
    msg = MIMEMultipart()
    msg['From'] = f"Grimset Studio <{gonderen_mail}>"
    msg['To'] = alici_mail
    msg['Subject'] = f"{plaka} Plakalı Aracınız İçin {tip} Teklifiniz"
    body = f"Merhaba {musteri_adi},\n\nGrimset Studio güvencesiyle {plaka} plakalı aracınız için hazırlanan {tip} poliçe teklifiniz ekteki PDF dosyasında sunulmuştur.\n\nToplam Prim: {prim}\n\nİyi çalışmalar dileriz."
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    part = MIMEApplication(pdf_bytes, Name=f"Grimset_Teklif_{plaka}.pdf")
    part['Content-Disposition'] = f'attachment; filename="Grimset_Teklif_{plaka}.pdf"'
    msg.attach(part)
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gonderen_mail, sifre)
        server.send_message(msg)
        server.quit()
        return True, "Teklif E-Postası başarıyla gönderildi!"
    except Exception as e: return False, f"Gönderim hatası: {e}"

def komisyon_hesapla(prim_tutari, police_tipi):
    if police_tipi in ["Kasko", "Filo Kasko", "DASK"]: oran = 0.15
    elif police_tipi in ["Zorunlu Trafik Sigortası", "Filo Zorunlu Trafik Sigortası"]: oran = 0.08
    else: oran = 0.10
    return int(prim_tutari * oran)

db = veritabani_yukle()

# --- YAN MENÜ VE ROL BAZLI ERİŞİM ---
st.sidebar.image("https://images.squarespace-cdn.com/content/v1/6055d01a61b2383be553b1b6/bd6d8e20-94d0-4e36-b552-6d2c4b574229/grimset+copy+copy+logo.png?format=1500w", width=150)
st.sidebar.markdown(f"**👤 Aktif Kullanıcı:** {st.session_state.kullanici_adi}")
if st.sidebar.button("🚪 Çıkış Yap", use_container_width=True):
    st.session_state.giris_yapildi = False
    st.rerun()
st.sidebar.markdown("---")

if st.session_state.rol in ["Admin", "Satis"]:
    st.sidebar.title("Modüller")
    # YENİ: "📌 Satış Hunisi (Kanban)" sekmesi satış ve admine eklendi.
    menu_secenekleri = ["📋 Kayıt & Ayıklama", "📝 Poliçe Atölyesi", "🏢 Kurumsal Filo (B2B)", "📌 Satış Hunisi (Kanban)", "🚗 Hasar Asistanı", "⚖️ Karşılaştırma"]
    if st.session_state.rol == "Admin":
        menu_secenekleri.extend(["⏰ Vade & Yenileme", "🎯 Kampanya Motoru", "🕵️‍♂️ AI Müşteri Profilleme", "📊 Finansal Dashboard"])
    sayfa = st.sidebar.radio("İşlem Seçin:", menu_secenekleri)
else:
    st.sidebar.title("Müşteri Paneli")
    menu_secenekleri = ["🏠 Poliçelerim", "🚗 Hasar Bildir"]
    sayfa = st.sidebar.radio("İşlem Seçin:", menu_secenekleri)

st.sidebar.markdown("---")
st.sidebar.caption("Grimset Studio © 2026")

# ----------------- MÜŞTERİ PORTALI SAYFALARI -----------------
if sayfa == "🏠 Poliçelerim" and st.session_state.rol == "Musteri":
    st.title(f"👋 Hoş Geldiniz, {st.session_state.kullanici_adi}")
    st.markdown(f"**{st.session_state.musteri_plaka}** plakalı aracınıza ait poliçe kayıtları aşağıdadır.")
    st.markdown("---")
    if sh:
        try:
            policeler = sh.worksheet("Üretilen Poliçeler").get_all_records()
            benim_policelerim = [p for p in policeler if str(p.get("Plaka", "")).replace(" ", "").upper() == st.session_state.musteri_plaka]
            if not benim_policelerim: st.info("Sistemde aracınıza ait kesilmiş poliçe bulunmamaktadır.")
            else:
                for p in benim_policelerim:
                    with st.container():
                        st.subheader(f"🛡️ {p.get('Poliçe Tipi', 'Poliçe')}")
                        c1, c2 = st.columns(2)
                        c1.write(f"**İşlem Tarihi:** {p.get('Tarih', '')}")
                        c1.write(f"**Ödenen Prim:** {p.get('Toplam Prim', '')}")
                        c2.write(f"**Teminat Özeti:**\n{p.get('Teminatlar', '')}")
                        pdf_data = pdf_olustur(p.get("Müşteri Adı"), p.get("Plaka"), p.get("Poliçe Tipi"), p.get("Teminatlar"), p.get("Toplam Prim"))
                        st.download_button("📄 Poliçemi İndir (PDF)", data=pdf_data, file_name=f"Police_{p.get('Plaka')}.pdf", mime="application/pdf", key=p.get('Tarih'))
                        st.markdown("---")
        except Exception as e: st.error(f"Veriler çekilirken hata oluştu: {e}")

elif sayfa == "🚗 Hasar Bildir" and st.session_state.rol == "Musteri":
    st.title("🚗 Kaza ve Hasar Bildirimi")
    st.info(f"**İşlem Yapılan Araç:** {st.session_state.musteri_plaka} | **Ruhsat Sahibi:** {st.session_state.kullanici_adi}")
    h_gorseller = st.file_uploader("Kaza ve Tutanak Fotoğrafları Yükle", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
    if h_gorseller:
        gorsel_sutunlari = st.columns(min(len(h_gorseller), 3))
        for idx, img in enumerate(h_gorseller[:3]): gorsel_sutunlari[idx].image(img, use_container_width=True)
    if st.button("🔍 Hasar Raporunu Oluştur ve Acenteme Gönder", type="primary", use_container_width=True):
        if h_gorseller:
            with st.spinner("Yapay zeka fotoğrafları inceliyor, rapor hazırlanıyor..."):
                analiz = kaza_analizi_yap(h_gorseller, st.session_state.musteri_plaka, st.session_state.kullanici_adi)
                st.success("Rapor başarıyla oluşturuldu ve Grimset Studio'ya iletildi!")
                st.info(analiz)
                try: sh.worksheet("Hasar Kayıtları").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state.kullanici_adi, st.session_state.musteri_plaka, analiz])
                except Exception as e: pass
        else: st.warning("Lütfen en az bir kaza fotoğrafı yükleyin.")

# ----------------- PERSONEL/ADMİN SAYFALARI -----------------
elif sayfa == "📋 Kayıt & Ayıklama":
    sol_panel, sag_panel = st.columns([1, 2], gap="large")
    with sol_panel:
        st.title("🛡️ Çoklu Evrak Okuma & Kayıt")
        st.markdown("---")
        if "son_ocr" not in st.session_state: st.session_state.son_ocr = None
        yuklenen_gorseller = st.file_uploader("Belge okutmak için resim seçin (Opsiyonel)", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
        if yuklenen_gorseller:
            gorsel_sutunlari = st.columns(len(yuklenen_gorseller))
            for idx, img in enumerate(yuklenen_gorseller): gorsel_sutunlari[idx].image(img, use_container_width=True)
            if st.button("Belgeleri Harmanla ve Ayıkla", use_container_width=True, type="primary"):
                with st.spinner("Gemini analiz ediyor..."):
                    ayiklanan = coklu_belge_oku(yuklenen_gorseller)
                    if ayiklanan and "Hata:" not in ayiklanan:
                        st.session_state.son_ocr = ayiklanan
                        st.success("Belgeler harmanlandı!")
                    else: st.error(ayiklanan)
        if st.session_state.son_ocr:
            st.text_area("Çapraz Analiz Sonuçları", value=st.session_state.son_ocr, height=220)
            
        st.markdown("### 📝 Müşteri Kayıt Formu")
        with st.form("crm_form"):
            m_adi = st.text_input("Ad Soyad")
            m_tel = st.text_input("Telefon (5XX...)")
            m_plaka = st.text_input("Plaka")
            m_vade = st.date_input("Poliçe Bitiş (Vade) Tarihi")
            if st.form_submit_button("Google Sheets'e Kaydet"):
                if m_adi and m_plaka and sh:
                    try:
                        zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        detay = st.session_state.son_ocr if st.session_state.son_ocr else "Manuel Kayıt"
                        sh.worksheet("Müşteri Portföyü").append_row([zaman, m_adi, m_tel, m_plaka, str(m_vade), detay])
                        st.success("Müşteri portföye eklendi!")
                        st.session_state.son_ocr = None
                    except Exception as e: st.error(f"Hata: {e}")
                else: st.warning("Ad ve Plaka zorunludur.")
    
    with sag_panel:
        st.subheader("🤖 Mevzuat Asistanı")
        sesli_metin = speech_to_text(language='tr-TR', start_prompt="🎙️ Konuş", stop_prompt="🛑 Durdur", use_container_width=True, just_once=True, key='STT')
        yazili_metin = st.chat_input("Veya sorunuzu buraya yazın...")
        aktif_soru = sesli_metin if sesli_metin else yazili_metin

        if "mesajlar" not in st.session_state: st.session_state.mesajlar = []
        for mesaj in st.session_state.mesajlar:
            with st.chat_message(mesaj["rol"]): st.markdown(mesaj["icerik"])
            
        if aktif_soru:
            st.session_state.mesajlar.append({"rol": "user", "icerik": aktif_soru})
            with st.chat_message("user"): st.markdown(aktif_soru)
            with st.chat_message("assistant"):
                with st.spinner("Taranıyor..."):
                    soru_vektoru = metni_vektore_cevir(aktif_soru)
                    skorlar = sorted([(benzerlik_hesapla(soru_vektoru, i["vektor"]), i["metin"]) for i in db], reverse=True)
                    baglam = "\n---\n".join([m for s, m in skorlar[:5]])
                    response = client.models.generate_content(model=TEXT_MODEL, contents=f"Bağlama göre cevapla:\n{baglam}\nSoru: {aktif_soru}")
                    st.markdown(response.text)
                    st.session_state.mesajlar.append({"rol": "assistant", "icerik": response.text})

elif sayfa == "📝 Poliçe Atölyesi":
    st.title("📝 Poliçe Atölyesi (Perakende)")
    st.markdown("---")
    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        p_musteri = st.text_input("Müşteri Adı Soyadı")
        p_tel = st.text_input("Telefon (WhatsApp için)")
        p_mail = st.text_input("Müşteri E-Posta Adresi")
        p_plaka = st.text_input("Araç Plakası")
        p_tip = st.selectbox("Poliçe Tipi", ["Kasko", "Zorunlu Trafik Sigortası", "DASK"])
        teminat_cam = st.checkbox("Sınırsız Orijinal Cam Değişimi", value=True)
        teminat_ikame = st.selectbox("İkame Araç Süresi", ["Yılda 2 Kez, 15 Gün", "Yılda 2 Kez, 7 Gün", "İkame Araç Yok"])
        teminat_imm = st.select_slider("İMM Limiti", options=["1.000.000 TL", "5.000.000 TL", "Sınırsız"], value="5.000.000 TL")
        
        st.markdown("---")
        st.markdown("### 🎁 Referans (Affiliate) İndirimi")
        kullanilan_ref = st.text_input("Müşteri bir tanıdığının kodunu getirdi mi?", placeholder="Örn: MEHMET-123 (Opsiyonel)")
        
    with col2:
        tahmini_prim = 15000 + (5000 if p_tip=="Kasko" else 0) + (1200 if teminat_cam else 0) + (3000 if teminat_imm=="Sınırsız" else 0)
        
        if kullanilan_ref:
            ref_indirim = int(tahmini_prim * 0.05)
            tahmini_prim -= ref_indirim
            st.success(f"🎉 Referans Kodu Onaylandı! Toplam fiyata {ref_indirim} TL ekstra indirim uygulandı.")
            
        piyasa_primi = int(tahmini_prim * 1.18)
        avantaj_tutari = piyasa_primi - tahmini_prim
        net_komisyon_tutari = komisyon_hesapla(tahmini_prim, p_tip)
        
        prim_yazisi = f"{tahmini_prim:,} TL"
        piyasa_yazisi = f"{piyasa_primi:,} TL"
        avantaj_yazisi = f"{avantaj_tutari:,} TL"
        net_komisyon_yazisi = f"{net_komisyon_tutari:,} TL"
        
        musteri_ozel_ref_kodu = ""
        if p_musteri and p_plaka:
            ilk_isim = p_musteri.split()[0].upper().replace(" ", "")
            plaka_son = p_plaka[-3:].upper() if len(p_plaka) >= 3 else "GRM"
            musteri_ozel_ref_kodu = f"{ilk_isim}-{plaka_son}"
        
        st.info("📊 **Fiyat & Rekabet Analizi**")
        c_m1, c_m2 = st.columns(2)
        c_m1.metric("Grimset Özel Fiyatı", prim_yazisi)
        c_m2.metric("Müşterinin Kazancı", avantaj_yazisi, delta=f"-{avantaj_tutari:,} TL Fark", delta_color="inverse")
        st.caption(f"*(Piyasa Ortalama Fiyatı: {piyasa_yazisi})*")
        
        teminat_ozeti = f"- Cam: {'Sınırsız' if teminat_cam else 'Muafiyetli'}\n- İkame: {teminat_ikame}\n- İMM: {teminat_imm}"
        if kullanilan_ref: teminat_ozeti += f"\n- Kullanılan Referans: {kullanilan_ref}"
        
        st.markdown("---")
        if st.button("💡 Yapay Zeka Satış Tüyosu Üret"):
            with st.spinner("Gemini satış stratejisi kurguluyor..."):
                prompt = f"Sen elit satış koçusun. Müşteri '{p_tip}' poliçesi alıyor. Plakası: {p_plaka}. Bu müşteriye gelirini artırmak için hangi ek ürünü satmalıyız? İkna edici 2 cümle öner."
                try: st.success(client.models.generate_content(model=TEXT_MODEL, contents=prompt).text)
                except: st.error("Asistan yanıt veremiyor.")
        st.markdown("---")
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💾 Google Sheets'e Kaydet", use_container_width=True):
                if p_musteri and p_plaka and sh:
                    try:
                        zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        sh.worksheet("Üretilen Poliçeler").append_row([zaman, p_musteri, p_plaka, p_tip, teminat_ozeti, prim_yazisi, st.session_state.kullanici_adi, net_komisyon_yazisi])
                        try: sh.worksheet("Müşteri Portföyü").append_row([zaman, p_musteri, p_tel, p_plaka, "", "Poliçe Atölyesinden Eklendi"])
                        except: pass
                        st.success("Poliçe kesildi ve portföye işlendi!")
                    except Exception as e: st.error(f"Hata: {e}")
        with col_btn2:
            if p_musteri and p_plaka:
                st.download_button("📄 PDF İndir", data=pdf_olustur(p_musteri, p_plaka, p_tip, teminat_ozeti, prim_yazisi, piyasa_yazisi, avantaj_yazisi, musteri_ozel_ref_kodu), file_name=f"Teklif_{p_plaka}.pdf", mime="application/pdf", use_container_width=True)
        
        if p_musteri and p_plaka:
            st.markdown("---")
            wp_mesaj = f"Merhaba {p_musteri},\nGrimset Studio güvencesiyle {p_plaka} plakalı aracınız için {p_tip} teklifiniz hazırlanmıştır.\n\nPiyasa Ortalaması: {piyasa_yazisi}\n*İndirimli Tutar:* {prim_yazisi}\nBu poliçeyle cebinizde kalan tutar: {avantaj_yazisi}!\n\n🎁 SİZE ÖZEL REFERANS KODUNUZ: {musteri_ozel_ref_kodu}\nBu kodu arkadaşlarınızla paylaşın, onlar bizden sigorta yaptırdığında bir sonraki poliçenizde anında %10 İNDİRİM kazanın!"
            wa_link = f"https://wa.me/90{p_tel.replace(' ', '').replace('+90', '').replace('0', '', 1)}?text={urllib.parse.quote(wp_mesaj)}" if p_tel else f"https://wa.me/?text={urllib.parse.quote(wp_mesaj)}"
            st.markdown(f'<a href="{wa_link}" target="_blank" style="text-decoration: none;"><div style="background-color: #25D366; color: white; text-align: center; padding: 10px; border-radius: 8px; font-weight: bold; margin-bottom: 10px;">💬 WhatsApp\'tan Gönder (Kod ile Beraber)</div></a>', unsafe_allow_html=True)

elif sayfa == "🏢 Kurumsal Filo (B2B)":
    st.title("🏢 Kurumsal Filo Yönetimi (B2B Teklif Motoru)")
    st.markdown("---")
    f_col1, f_col2 = st.columns([1, 1], gap="large")
    with f_col1:
        f_firma = st.text_input("Kurumsal Firma Adı")
        f_tip = st.selectbox("Filo Sigorta Tipi", ["Filo Kasko", "Filo Zorunlu Trafik Sigortası"])
        girilen_plakalar = st_tags(label='**Araç Plakalarını Girin**', text='Plakayı yazıp Enter tuşuna basın', value=[], suggestions=['34ABC123', '06DEF456'], key='filo_plakalar')
    with f_col2:
        if f_firma and girilen_plakalar:
            plakalar = [p.strip().upper() for p in girilen_plakalar if p.strip()]
            arac_sayisi = len(plakalar)
            if arac_sayisi > 0:
                taban_fiyat = 20000 if f_tip == "Filo Kasko" else 8000
                indirim_orani = min(arac_sayisi * 0.02, 0.30)
                arac_basi_fiyat = int(taban_fiyat * (1 - indirim_orani))
                toplam_filo_primi = arac_basi_fiyat * arac_sayisi
                net_komisyon_filo = komisyon_hesapla(toplam_filo_primi, f_tip)
                
                st.success(f"**{arac_sayisi} Adet Araç Başarıyla Eşleştirildi!**")
                st.info(f"Uygulanan İndirim: **%{int(indirim_orani*100)}** | Toplam Prim: **{toplam_filo_primi:,} TL**")
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("💾 Sisteme Kaydet", use_container_width=True, type="primary"):
                        if sh:
                            try:
                                sh.worksheet("Filo Teklifleri").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f_firma, arac_sayisi, ", ".join(plakalar), f_tip, f"{toplam_filo_primi:,} TL", st.session_state.kullanici_adi, f"{net_komisyon_filo:,} TL"])
                                st.success("B2B Filo teklifi kaydedildi!")
                            except Exception as e: st.error(f"Kayıt Hatası: {e}")
                with col_btn2:
                    st.download_button("📄 PDF İndir", data=filo_pdf_olustur(f_firma, plakalar, f_tip, toplam_filo_primi), file_name=f"Grimset_{f_firma}.pdf", mime="application/pdf", use_container_width=True)

# --- YENİ MODÜL: SATIŞ HUNİSİ (KANBAN) ---
elif sayfa == "📌 Satış Hunisi (Kanban)":
    st.title("📌 Akıllı Satış Hunisi (Kanban Panosu)")
    st.markdown("Müşteri adaylarınızı aşamalar arasında sürükleyerek (seçerek) takip edin. Satış kapatma oranınızı artırın!")
    st.markdown("---")
    
    if sh:
        try:
            ws_huni = sh.worksheet("Satış Hunisi")
            
            # --- YENİ ADAY EKLEME FORMU ---
            with st.expander("➕ Yeni Satış Fırsatı (Aday) Ekle"):
                with st.form("huni_form"):
                    h_isim = st.text_input("Müşteri Adı")
                    h_tel = st.text_input("Telefon")
                    h_konu = st.text_input("İlgilendiği Ürün (Kasko, TSS, Filo vs.)")
                    h_tutar = st.text_input("Tahmini Tutar (Opsiyonel)")
                    
                    if st.form_submit_button("Adayı Huniye Ekle"):
                        if h_isim and h_konu:
                            zaman_id = datetime.now().strftime("%Y%m%d%H%M%S") # Benzersiz ID
                            tarih = datetime.now().strftime("%Y-%m-%d")
                            ws_huni.append_row([zaman_id, tarih, h_isim, h_tel, h_konu, h_tutar, "Yeni Aday", st.session_state.kullanici_adi])
                            st.success(f"{h_isim} aday olarak eklendi!")
                            st.rerun()
                        else:
                            st.warning("Lütfen Müşteri Adı ve İlgilendiği Ürünü girin.")
            
            st.markdown("### 📊 Aktif Fırsatlar Tablosu")
            
            # Verileri Gspread'den çek ve başlıkları ayır
            tum_veriler = ws_huni.get_all_values()
            
            if len(tum_veriler) > 1:
                satirlar = tum_veriler[1:] # İlk satır başlıklar
                
                # Streamlit Kolonlarını Oluştur
                k1, k2, k3, k4 = st.columns(4)
                
                k1.markdown("<div style='background-color: #2980b9; padding: 10px; border-radius: 5px; text-align: center; color: white;'><b>🆕 Yeni Aday</b></div><br>", unsafe_allow_html=True)
                k2.markdown("<div style='background-color: #f39c12; padding: 10px; border-radius: 5px; text-align: center; color: white;'><b>⏳ Görüşülüyor</b></div><br>", unsafe_allow_html=True)
                k3.markdown("<div style='background-color: #8e44ad; padding: 10px; border-radius: 5px; text-align: center; color: white;'><b>📄 Teklif Verildi</b></div><br>", unsafe_allow_html=True)
                k4.markdown("<div style='background-color: #27ae60; padding: 10px; border-radius: 5px; text-align: center; color: white;'><b>🏆 Kazanıldı</b></div><br>", unsafe_allow_html=True)
                
                # Kayıtları aşamasına göre ilgili sütuna dağıt
                for idx, row in enumerate(satirlar):
                    # Olası eksik sütun hatalarını önlemek için kontrol
                    if len(row) < 8: continue
                    
                    r_id, r_tar, r_isim, r_tel, r_konu, r_tut, r_asama, r_sorumlu = row
                    
                    # Hangi sütuna gideceğini belirle
                    hedef_kolon = None
                    if r_asama == "Yeni Aday": hedef_kolon = k1
                    elif r_asama == "Görüşülüyor": hedef_kolon = k2
                    elif r_asama == "Teklif Verildi": hedef_kolon = k3
                    elif r_asama == "Kazanıldı": hedef_kolon = k4
                    else: continue # 'İptal' edilenleri ekranda göstermeyebiliriz
                    
                    with hedef_kolon:
                        with st.container(border=True):
                            st.markdown(f"**👤 {r_isim}**")
                            st.caption(f"🎯 Hedef: {r_konu}")
                            if r_tut: st.caption(f"💰 Tutar: {r_tut}")
                            st.caption(f"💼 Sorumlu: {r_sorumlu}")
                            
                            # Aşama Değiştirme Selectbox'ı
                            # Selectbox değiştiğinde veritabanındaki (idx + 2) numaralı satırın 7. sütununu güncelliyoruz
                            secili_index = ["Yeni Aday", "Görüşülüyor", "Teklif Verildi", "Kazanıldı", "İptal Edildi"].index(r_asama) if r_asama in ["Yeni Aday", "Görüşülüyor", "Teklif Verildi", "Kazanıldı", "İptal Edildi"] else 0
                            
                            yeni_asama = st.selectbox(
                                "Durumu Güncelle", 
                                ["Yeni Aday", "Görüşülüyor", "Teklif Verildi", "Kazanıldı", "İptal Edildi"],
                                index=secili_index,
                                key=f"asama_{r_id}"
                            )
                            
                            if yeni_asama != r_asama:
                                ws_huni.update_cell(idx + 2, 7, yeni_asama) # Gspread'de satırlar 1'den başlar (idx+2)
                                st.rerun()
            else:
                st.info("Sistemde henüz takip edilen bir satış fırsatı bulunmuyor. Yukarıdan yeni aday ekleyebilirsiniz.")
                
        except Exception as e:
            st.warning(f"Kanban verileri yüklenirken hata oluştu: {e}")

elif sayfa == "🚗 Hasar Asistanı":
    st.title("🚗 Kaza ve Hasar Destek Asistanı")
    st.markdown("---")
    h_col1, h_col2 = st.columns([1, 2], gap="large")
    with h_col1:
        h_isim = st.text_input("Müşteri Adı Soyadı")
        h_plaka = st.text_input("Araç Plakası")
        h_gorseller = st.file_uploader("Kaza ve Tutanak Fotoğrafları", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
        if h_gorseller:
            gorsel_sutunlari = st.columns(min(len(h_gorseller), 3))
            for idx, img in enumerate(h_gorseller[:3]): gorsel_sutunlari[idx].image(img, use_container_width=True)
        if st.button("🔍 Hasarı Analiz Et", type="primary", use_container_width=True):
            if h_isim and h_plaka and h_gorseller:
                with st.spinner("Analiz Yapılıyor..."):
                    st.session_state.son_kaza_analizi = kaza_analizi_yap(h_gorseller, h_plaka, h_isim)
            else: st.warning("İsim, Plaka ve fotoğraf gerekli.")
    with h_col2:
        if "son_kaza_analizi" in st.session_state and st.session_state.son_kaza_analizi:
            st.success("Rapor Başarıyla Oluşturuldu!")
            st.info(st.session_state.son_kaza_analizi)
            if st.button("💾 Google Sheets'e Kaydet"):
                try:
                    sh.worksheet("Hasar Kayıtları").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), h_isim, h_plaka, st.session_state.son_kaza_analizi])
                    st.success("Kaydedildi!")
                except Exception as e: st.error(f"Hata: {e}")

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

elif sayfa == "⏰ Vade & Yenileme" and st.session_state.rol == "Admin":
    st.title("⏰ Akıllı Vade & Yenileme Panosu")
    st.markdown("---")
    if sh:
        try:
            musteriler = sh.worksheet("Müşteri Portföyü").get_all_records()
            if musteriler:
                bugun = datetime.now().date()
                yaklasanlar = []
                for m in musteriler:
                    vade_str = str(m.get('Vade Tarihi', ''))
                    if vade_str:
                        try:
                            vade_tarihi = datetime.strptime(vade_str, "%Y-%m-%d").date()
                            kalan_gun = (vade_tarihi - bugun).days
                            if kalan_gun <= 15:
                                m['kalan_gun'] = kalan_gun
                                yaklasanlar.append(m)
                        except: pass
                if yaklasanlar:
                    yaklasanlar.sort(key=lambda x: x['kalan_gun'])
                    for y in yaklasanlar:
                        k_gun = y['kalan_gun']
                        durum_renk = "🔴 GEÇTİ" if k_gun < 0 else f"🟡 {k_gun} Gün"
                        with st.expander(f"{durum_renk} | {y.get('Müşteri Adı', '')} - Plaka: {y.get('Plaka', '')}"):
                            st.write(f"Tel: {y.get('Telefon', '')} | Vade: {y.get('Vade Tarihi', '')}")
                else: st.success("Süresi yaklaşan poliçe yok.")
        except Exception as e: st.warning(f"Hata: {e}")

elif sayfa == "🎯 Kampanya Motoru" and st.session_state.rol == "Admin":
    st.title("🎯 Toplu Filtreleme ve SMS/Mesaj Kampanya Motoru")
    st.markdown("---")
    if sh:
        try:
            uretimler = sh.worksheet("Üretilen Poliçeler").get_all_records()
            musteriler_crm = sh.worksheet("Müşteri Portföyü").get_all_records()
            if not uretimler or not musteriler_crm:
                st.warning("Kampanya yapmak için sistemde kayıt bulunmalıdır.")
            else:
                df_police = pd.DataFrame(uretimler)
                df_musteri = pd.DataFrame(musteriler_crm)
                if 'Plaka' in df_police.columns and 'Plaka' in df_musteri.columns:
                    df_hedef = pd.merge(df_police, df_musteri[['Plaka', 'Telefon']], on='Plaka', how='left')
                    df_hedef = df_hedef.drop_duplicates(subset=['Plaka'])
                    col_f1, col_f2 = st.columns(2)
                    with col_f1:
                        hedef_urun = st.selectbox("Hangi Poliçeye Sahip Olanları Hedefleyelim?", ["Tümü"] + list(df_hedef['Poliçe Tipi'].unique()))
                    if hedef_urun != "Tümü": df_filtrelenmis = df_hedef[df_hedef['Poliçe Tipi'] == hedef_urun]
                    else: df_filtrelenmis = df_hedef
                    if not df_filtrelenmis.empty:
                        varsayilan_mesaj = f"Merhaba {{isim}} Bey/Hanım,\nGrimset Studio olarak {{plaka}} plakalı aracınıza kestiğimiz {hedef_urun} poliçeniz dolayısıyla size özel indirim tanımlanmıştır."
                        kampanya_metni = st.text_area("Mesaj Metni", value=varsayilan_mesaj, height=150)
                        st.markdown("---")
                        st.subheader("3. Gönderimi Başlat")
                        for index, row in df_filtrelenmis.iterrows():
                            isim = str(row.get('Müşteri Adı', 'Müşterimiz'))
                            plaka = str(row.get('Plaka', 'Aracınız'))
                            tel = str(row.get('Telefon', ''))
                            ozel_mesaj = kampanya_metni.replace("{isim}", isim).replace("{plaka}", plaka)
                            with st.expander(f"👤 {isim} | {plaka}"):
                                st.write(f"**Önizleme:**\n{ozel_mesaj}")
                                if tel and tel != 'nan':
                                    wa_link = f"https://wa.me/90{tel.replace(' ', '').replace('+90', '').replace('0', '', 1)}?text={urllib.parse.quote(ozel_mesaj)}"
                                    st.markdown(f'<a href="{wa_link}" target="_blank" style="text-decoration: none;"><div style="background-color: #25D366; color: white; text-align: center; padding: 5px; border-radius: 5px; font-weight: bold;">💬 Gönder</div></a>', unsafe_allow_html=True)
                else: st.warning("Plaka eşleşmesi yapılamadı.")
        except Exception as e: st.warning(f"Hata: {e}")

elif sayfa == "🕵️‍♂️ AI Müşteri Profilleme" and st.session_state.rol == "Admin":
    st.title("🕵️‍♂️ Yapay Zeka Müşteri Risk & Sadakat Profillemesi")
    st.markdown("---")
    if sh:
        try:
            uretimler = sh.worksheet("Üretilen Poliçeler").get_all_records()
            if not uretimler:
                st.warning("Analiz edilecek poliçe verisi bulunmuyor.")
            else:
                df_police = pd.DataFrame(uretimler)
                musteri_listesi = df_police['Müşteri Adı'].dropna().unique()
                if len(musteri_listesi) > 0:
                    secilen_musteri = st.selectbox("Müşteri Seçin:", musteri_listesi)
                    if st.button("🧠 Profili Çıkar", type="primary", use_container_width=True):
                        with st.spinner("İnceleniyor..."):
                            m_data = df_police[df_police['Müşteri Adı'] == secilen_musteri]
                            policeler_str = ", ".join(m_data['Poliçe Tipi'].astype(str).tolist())
                            plakalar_str = ", ".join(m_data['Plaka'].astype(str).unique().tolist())
                            toplam_harcama = sum([int(str(row.get('Toplam Prim', '0')).replace(' TL', '').replace(',', '')) for index, row in m_data.iterrows() if str(row.get('Toplam Prim', '0')).replace(' TL', '').replace(',', '').isdigit()])
                            prompt = f"Sen Grimset Studio'nun elit sigorta aktüerisin. Müşteri: {secilen_musteri}, Araçlar: {plakalar_str}, İşlemler: {policeler_str}, Şirkete Kazandırdığı: {toplam_harcama} TL. 1. Sadakat Puanı, 2. Risk Puanı, 3. Profil Özeti, 4. VIP Satış Stratejisi çıkar."
                            try:
                                st.success(f"**{secilen_musteri}** için profilleme tamamlandı!")
                                st.info(client.models.generate_content(model=TEXT_MODEL, contents=prompt).text)
                            except Exception as e: st.error(f"Hata: {e}")
        except Exception as e: st.warning(f"Hata: {e}")

elif sayfa == "📊 Finansal Dashboard" and st.session_state.rol == "Admin":
    st.title("📊 Yönetici Finansal Dashboard (Kâr/Zarar Merkezi)")
    st.markdown("---")
    if sh:
        try:
            policeler = sh.worksheet("Üretilen Poliçeler").get_all_records()
            if not policeler: st.info("Veri bulunmuyor."); st.stop()
            df = pd.DataFrame(policeler)
            df['Saf Prim'] = df['Toplam Prim'].astype(str).str.replace(' TL', '').str.replace(',', '').astype(float)
            
            if 'Net Komisyon' not in df.columns: df['Net Komisyon'] = df['Saf Prim'] * 0.10
            else: df['Net Komisyon'] = df['Net Komisyon'].astype(str).str.replace(' TL', '').str.replace(',', '').replace('', '0').astype(float)
                
            if 'Satış Temsilcisi' not in df.columns: df['Satış Temsilcisi'] = 'Bilinmiyor'
            df['Satış Temsilcisi'] = df['Satış Temsilcisi'].replace('', 'Bilinmiyor').fillna('Bilinmiyor')
            
            toplam_ciro = df['Saf Prim'].sum()
            toplam_komisyon = df['Net Komisyon'].sum()
            
            st.markdown(f"""
            <div style="background: linear-gradient(90deg, #1A2980 0%, #26D0CE 100%); padding: 20px; border-radius: 10px; color: white; text-align: center; margin-bottom: 20px;">
                <h2 style="margin:0; color: white;">💰 GRIMSET STUDIO NET KAZANÇ (KOMİSYON)</h2>
                <h1 style="margin:0; font-size: 3rem; color: #00FF7F;">{int(toplam_komisyon):,} TL</h1>
                <p style="margin:0; opacity: 0.8;">Bu tutar şirketinizin kasasına giren net, temiz kârdır.</p>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            col1.metric("💼 Toplam Kesilen Poliçe", f"{len(df)} Adet")
            col2.metric("📈 Toplam Sigorta Hacmi (Ciro)", f"{int(toplam_ciro):,} TL")
            col3.metric("🏆 En Çok Satılan", str(df['Poliçe Tipi'].mode()[0]))
            
            st.markdown("---")
            st.subheader("🏆 Satış Ekibi Kâr Getirisi (Kim Ne Kadar Kazandırdı?)")
            satis_performansi = df.groupby('Satış Temsilcisi')['Net Komisyon'].sum().reset_index().sort_values(by='Net Komisyon', ascending=False)
            st.plotly_chart(px.bar(satis_performansi, x='Satış Temsilcisi', y='Net Komisyon', text_auto='.2s', color='Satış Temsilcisi'), use_container_width=True)
            
            st.markdown("---")
            g_col1, g_col2 = st.columns(2)
            with g_col1:
                st.plotly_chart(px.pie(df, names='Poliçe Tipi', values='Net Komisyon', hole=0.4, color_discrete_sequence=px.colors.sequential.Teal, title="Ürünlere Göre Net Kâr Dağılımı"), use_container_width=True)
            with g_col2:
                df['Kısa Tarih'] = pd.to_datetime(df['Tarih']).dt.date
                st.plotly_chart(px.bar(df.groupby('Kısa Tarih')['Net Komisyon'].sum().reset_index(), x='Kısa Tarih', y='Net Komisyon', text_auto='.2s', color_discrete_sequence=['#4CAF50'], title="Günlük Net Kâr Akışı"), use_container_width=True)
                
            st.markdown("---")
            st.subheader("Son Kesilen Poliçeler")
            st.dataframe(df[['Tarih', 'Satış Temsilcisi', 'Müşteri Adı', 'Poliçe Tipi', 'Toplam Prim', 'Net Komisyon']].tail(10).iloc[::-1], use_container_width=True)
        except Exception as e: st.warning(f"Hata: {e}")
