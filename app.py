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
            st.info("Poliçelerinizi görüntülemek için T.C. Kimlik Numaranızı (Plaka yerine) veya Araç Plakanızı ve sisteme kayıtlı telefon numaranızı girin.")
            m_plaka_giris = st.text_input("Plaka veya T.C. Kimlik No", placeholder="Örn: 34ABC123 veya 12345678901")
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
                        if not giris_basarili: st.error("Sistemde bu bilgi ve telefon numarasıyla eşleşen kayıt bulunamadı.")
                    except Exception as e: st.error(f"Veritabanı kontrol hatası: {e}")
                else: st.warning("Lütfen bilgilerinizi eksiksiz girin.")
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

def pdf_olustur(musteri, plaka, tip, teminatlar, prim, piyasa_fiyati=None, kazanc=None, ref_kodu=None, dil="Türkçe"):
    sozluk = {
        "Türkçe": {
            "baslik": "GRIMSET STUDIO - POLICE TEKLIFI", "musteri": "Musteri", "plaka": "Arac Plakasi / T.C. No", "tip": "Police Tipi",
            "teminatlar": "Secili Teminatlar & Ozet:", "grimset_fiyat": "Grimset Ozel Primi:", "piyasa_fiyat": "Piyasa Ortalamasi:",
            "kazanc": "Sizin Kazanciniz:", "ref_baslik": "Size Ozel Kazandiran Paylasim Kodunuz!",
            "ref_metin": "Bu kodu arkadaslarinizla paylasin. Arkadaslariniz bu kodla aninda %5 indirim kazanirken, siz de bir sonraki police yenilemenizde %10 indirim kazanin!"
        },
        "English": {
            "baslik": "GRIMSET STUDIO - INSURANCE QUOTE", "musteri": "Customer", "plaka": "License Plate / ID", "tip": "Policy Type",
            "teminatlar": "Selected Coverages & Summary:", "grimset_fiyat": "Grimset Special Premium:", "piyasa_fiyat": "Market Average:",
            "kazanc": "Your Total Savings:", "ref_baslik": "Your Exclusive Affiliate Code!",
            "ref_metin": "Share this code with friends. They get a 5% instant discount, and you get a 10% discount on your next renewal!"
        },
        "Deutsch": {
            "baslik": "GRIMSET STUDIO - VERSICHERUNGSANGEBOT", "musteri": "Kunde", "plaka": "Kennzeichen / ID", "tip": "Versicherungsart",
            "teminatlar": "Gewaehlter Schutz:", "grimset_fiyat": "Grimset Spezialpraemie:", "piyasa_fiyat": "Marktdurchschnitt:",
            "kazanc": "Ihre Ersparnis:", "ref_baslik": "Ihr exklusiver Empfehlungscode!",
            "ref_metin": "Teilen Sie diesen Code. Freunde erhalten 5% Rabatt, und Sie erhalten 10% Rabatt auf Ihre naechste Verlaengerung!"
        },
        "Français": {
            "baslik": "GRIMSET STUDIO - DEVIS D'ASSURANCE", "musteri": "Client", "plaka": "Plaque / ID", "tip": "Type de Police",
            "teminatlar": "Garanties Choisies:", "grimset_fiyat": "Prime Speciale Grimset:", "piyasa_fiyat": "Moyenne du Marche:",
            "kazanc": "Vos Economies:", "ref_baslik": "Votre Code de Parrainage Exclusif!",
            "ref_metin": "Partagez ce code. Vos amis obtiennent 5% de reduction, et vous obtenez 10% sur votre prochain renouvellement!"
        }
    }
    d = sozluk.get(dil, sozluk["Türkçe"])
    
    tip_cevirileri = {
        "English": {"Kasko": "Comprehensive Insurance", "Zorunlu Trafik Sigortası": "Compulsory Traffic Insurance", "DASK": "Earthquake Insurance", "Tamamlayıcı Sağlık Sigortası (TSS)": "Supplementary Health Insurance", "Özel Sağlık Sigortası (ÖSS)": "Private Health Insurance"},
        "Deutsch": {"Kasko": "Vollkaskoversicherung", "Zorunlu Trafik Sigortası": "Kfz-Haftpflicht", "DASK": "Erdbebenversicherung", "Tamamlayıcı Sağlık Sigortası (TSS)": "Zusatzkrankenversicherung", "Özel Sağlık Sigortası (ÖSS)": "Private Krankenversicherung"},
        "Français": {"Kasko": "Assurance Tous Risques", "Zorunlu Trafik Sigortası": "Assurance au Tiers", "DASK": "Assurance Tremblement de Terre", "Tamamlayıcı Sağlık Sigortası (TSS)": "Complémentaire Santé", "Özel Sağlık Sigortası (ÖSS)": "Assurance Santé Privée"}
    }
    if dil != "Türkçe" and tip in tip_cevirileri[dil]: tip = tip_cevirileri[dil][tip]

    pdf = FPDF()
    pdf.add_page()
    tr_map = str.maketrans("ğüşöçıİĞÜŞÖÇ", "gusociIGUSOC")
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, d["baslik"], ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"{d['musteri']}: {musteri.translate(tr_map)}", ln=True)
    pdf.cell(0, 10, f"{d['plaka']}: {plaka.translate(tr_map)}", ln=True)
    pdf.cell(0, 10, f"{d['tip']}: {tip.translate(tr_map)}", ln=True)
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, d["teminatlar"], ln=True)
    pdf.set_font("Arial", "", 10)
    pdf.multi_cell(0, 8, teminatlar.translate(tr_map))
    pdf.ln(10)
    
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, f"{d['grimset_fiyat']} {prim}", ln=True)
    
    if piyasa_fiyati and kazanc:
        pdf.ln(2)
        pdf.set_font("Arial", "", 11)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 10, f"{d['piyasa_fiyat']} {piyasa_fiyati}", ln=True)
        pdf.set_text_color(0, 128, 0)
        pdf.set_font("Arial", "B", 13)
        pdf.cell(0, 10, f"{d['kazanc']} {kazanc}", ln=True)
        pdf.set_text_color(0, 0, 0)
        
    if ref_kodu:
        pdf.ln(15)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, d["ref_baslik"], ln=True, fill=True)
        pdf.set_font("Arial", "B", 14)
        pdf.set_text_color(255, 69, 0)
        pdf.cell(0, 10, f"CODE: {ref_kodu}", ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "", 10)
        pdf.multi_cell(0, 8, d["ref_metin"])

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

def eposta_gonder(alici_mail, musteri_adi, plaka, tip, teminatlar, prim, pdf_bytes, dil="Türkçe"):
    gonderen_mail = st.secrets.get("SMTP_EMAIL")
    sifre = st.secrets.get("SMTP_PASSWORD")
    if not gonderen_mail or not sifre: return False, "E-Posta ayarları eksik!"
    
    konular = {
        "Türkçe": f"{plaka} Poliçe / Teklifiniz",
        "English": f"Your {tip} Quote for {plaka}",
        "Deutsch": f"Ihr {tip} Angebot für {plaka}",
        "Français": f"Votre devis {tip} pour {plaka}"
    }
    
    mesajlar = {
        "Türkçe": f"Merhaba {musteri_adi},\n\nGrimset Studio güvencesiyle {plaka} için hazırlanan {tip} teklifiniz ektedir.\n\nToplam Prim: {prim}\n\nİyi çalışmalar dileriz.",
        "English": f"Hello {musteri_adi},\n\nYour {tip} quote for {plaka} by Grimset Studio is attached.\n\nTotal Premium: {prim}\n\nBest regards.",
        "Deutsch": f"Hallo {musteri_adi},\n\nIhr {tip} Angebot für {plaka} von Grimset Studio ist beigefügt.\n\nGesamtprämie: {prim}\n\nMit freundlichen Grüßen.",
        "Français": f"Bonjour {musteri_adi},\n\nVotre devis {tip} pour {plaka} par Grimset Studio est en pièce jointe.\n\nPrime Totale: {prim}\n\nCordialement."
    }
    
    msg = MIMEMultipart()
    msg['From'] = f"Grimset Studio <{gonderen_mail}>"
    msg['To'] = alici_mail
    msg['Subject'] = konular.get(dil, konular["Türkçe"])
    msg.attach(MIMEText(mesajlar.get(dil, mesajlar["Türkçe"]), 'plain', 'utf-8'))
    part = MIMEApplication(pdf_bytes, Name=f"Grimset_Quote_{plaka}.pdf")
    part['Content-Disposition'] = f'attachment; filename="Grimset_Quote_{plaka}.pdf"'
    msg.attach(part)
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gonderen_mail, sifre)
        server.send_message(msg)
        server.quit()
        return True, "Teklif başarıyla gönderildi!"
    except Exception as e: return False, f"Gönderim hatası: {e}"

def komisyon_hesapla(prim_tutari, police_tipi):
    # Sağlık Sigortaları genellikle yüksek komisyonludur
    if police_tipi in ["Kasko", "Filo Kasko", "DASK", "Tamamlayıcı Sağlık Sigortası (TSS)", "Özel Sağlık Sigortası (ÖSS)"]: oran = 0.15
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
    # YENİ: Sağlık Sigortası Modülü Eklendi
    menu_secenekleri = ["📋 Kayıt & Ayıklama", "📝 Poliçe Atölyesi", "🏥 Sağlık (TSS/ÖSS)", "🏢 Kurumsal Filo (B2B)", "📌 Satış Hunisi (Kanban)", "🚗 Hasar Asistanı"]
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
    st.markdown(f"**{st.session_state.musteri_plaka}** T.C. / Plaka bilgisine ait poliçe kayıtları aşağıdadır.")
    st.markdown("---")
    if sh:
        try:
            policeler = sh.worksheet("Üretilen Poliçeler").get_all_records()
            benim_policelerim = [p for p in policeler if str(p.get("Plaka", "")).replace(" ", "").upper() == st.session_state.musteri_plaka]
            if not benim_policelerim: st.info("Sistemde tarafınıza ait kesilmiş poliçe bulunmamaktadır.")
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
            m_plaka = st.text_input("Plaka veya T.C. Kimlik No")
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
                else: st.warning("Ad ve Plaka/T.C. zorunludur.")
    
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
    st.title("📝 Poliçe Atölyesi (Perakende Oto/Dask)")
    st.markdown("---")
    
    secilen_dil = st.radio("🌍 Müşteri İletişim Dili (PDF ve Mesaj Şablonu)", ["Türkçe", "English", "Deutsch", "Français"], horizontal=True)
    st.markdown("---")
    
    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        p_musteri = st.text_input("Müşteri Adı Soyadı")
        p_tel = st.text_input("Telefon (WhatsApp için)")
        p_mail = st.text_input("Müşteri E-Posta Adresi")
        p_plaka = st.text_input("Araç Plakası veya Adres Kodu (DASK)")
        p_tip = st.selectbox("Poliçe Tipi", ["Kasko", "Zorunlu Trafik Sigortası", "DASK"])
        teminat_cam = st.checkbox("Sınırsız Orijinal Cam Değişimi", value=True)
        teminat_ikame = st.selectbox("İkame Araç Süresi", ["Yılda 2 Kez, 15 Gün", "Yılda 2 Kez, 7 Gün", "İkame Araç Yok"])
        teminat_imm = st.select_slider("İMM Limiti", options=["1.000.000 TL", "5.000.000 TL", "Sınırsız"], value="5.000.000 TL")
        st.markdown("---")
        st.markdown("### 🎁 Referans İndirimi")
        kullanilan_ref = st.text_input("Müşteri bir kod getirdi mi?", placeholder="Örn: MEHMET-123 (Opsiyonel)")
        
    with col2:
        tahmini_prim = 15000 + (5000 if p_tip=="Kasko" else 0) + (1200 if teminat_cam else 0) + (3000 if teminat_imm=="Sınırsız" else 0)
        if p_tip == "DASK": tahmini_prim = 1200
        
        if kullanilan_ref:
            ref_indirim = int(tahmini_prim * 0.05)
            tahmini_prim -= ref_indirim
            st.success(f"🎉 Referans İndirimi Uygulandı: -{ref_indirim} TL")
            
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
        
        cam_text = "Sınırsız" if teminat_cam else "Muafiyetli"
        if secilen_dil == "English": teminat_ozeti = f"- Glass: {cam_text}\n- Replacement Car: {teminat_ikame}\n- Liability Limit: {teminat_imm}"
        elif secilen_dil == "Deutsch": teminat_ozeti = f"- Glas: {cam_text}\n- Ersatzwagen: {teminat_ikame}\n- Haftpflichtlimit: {teminat_imm}"
        elif secilen_dil == "Français": teminat_ozeti = f"- Bris de Glace: {cam_text}\n- Vehicule Remplacement: {teminat_ikame}\n- Limite Responsabilite: {teminat_imm}"
        else: teminat_ozeti = f"- Cam: {cam_text}\n- İkame: {teminat_ikame}\n- İMM: {teminat_imm}"
        
        if kullanilan_ref: teminat_ozeti += f"\n- Ref: {kullanilan_ref}"
        
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
                        try: sh.worksheet("Müşteri Portföyü").append_row([zaman, p_musteri, p_tel, p_plaka, "", "Poliçe Atölyesi"])
                        except: pass
                        st.success("Poliçe kesildi!")
                    except Exception as e: st.error(f"Hata: {e}")
        with col_btn2:
            if p_musteri and p_plaka:
                st.download_button("📄 PDF İndir (" + secilen_dil + ")", data=pdf_olustur(p_musteri, p_plaka, p_tip, teminat_ozeti, prim_yazisi, piyasa_yazisi, avantaj_yazisi, musteri_ozel_ref_kodu, dil=secilen_dil), file_name=f"Grimset_{secilen_dil}_{p_plaka}.pdf", mime="application/pdf", use_container_width=True)
        
        if p_musteri and p_plaka:
            st.markdown("---")
            if secilen_dil == "English":
                wp_mesaj = f"Hello {p_musteri},\nYour {p_tip} quote for vehicle {p_plaka} by Grimset Studio is ready.\n\nMarket Average: {piyasa_yazisi}\n*Grimset Discounted Price:* {prim_yazisi}\nYour total savings: {avantaj_yazisi}!\n\n🎁 EXCLUSIVE AFFILIATE CODE: {musteri_ozel_ref_kodu}\nShare this code with friends for a 10% discount on your next renewal!"
            elif secilen_dil == "Deutsch":
                wp_mesaj = f"Hallo {p_musteri},\nIhr {p_tip} Angebot für Fahrzeug {p_plaka} von Grimset Studio ist fertig.\n\nMarktdurchschnitt: {piyasa_yazisi}\n*Grimset Rabattpreis:* {prim_yazisi}\nIhre Ersparnis: {avantaj_yazisi}!\n\n🎁 IHR EMPFEHLUNGSCODE: {musteri_ozel_ref_kodu}\nTeilen Sie diesen Code, um 10% Rabatt auf Ihre nächste Verlängerung zu erhalten!"
            elif secilen_dil == "Français":
                wp_mesaj = f"Bonjour {p_musteri},\nVotre devis {p_tip} pour le véhicule {p_plaka} par Grimset Studio est prêt.\n\nMoyenne du marché: {piyasa_yazisi}\n*Prix réduit Grimset:* {prim_yazisi}\nVos économies: {avantaj_yazisi}!\n\n🎁 CODE DE PARRAINAGE: {musteri_ozel_ref_kodu}\nPartagez ce code avec vos amis pour obtenir 10% de réduction sur votre prochain renouvellement!"
            else:
                wp_mesaj = f"Merhaba {p_musteri},\nGrimset Studio güvencesiyle {p_plaka} plakalı aracınız için {p_tip} teklifiniz hazırlanmıştır.\n\nPiyasa Ortalaması: {piyasa_yazisi}\n*İndirimli Tutar:* {prim_yazisi}\nKazancınız: {avantaj_yazisi}!\n\n🎁 REFERANS KODUNUZ: {musteri_ozel_ref_kodu}\nBu kodu arkadaşlarınızla paylaşarak %10 İNDİRİM kazanın!"
                
            wa_link = f"https://wa.me/90{p_tel.replace(' ', '').replace('+90', '').replace('0', '', 1)}?text={urllib.parse.quote(wp_mesaj)}" if p_tel else f"https://wa.me/?text={urllib.parse.quote(wp_mesaj)}"
            st.markdown(f'<a href="{wa_link}" target="_blank" style="text-decoration: none;"><div style="background-color: #25D366; color: white; text-align: center; padding: 10px; border-radius: 8px; font-weight: bold; margin-bottom: 10px;">💬 WhatsApp Gönder ({secilen_dil})</div></a>', unsafe_allow_html=True)

# --- YENİ MODÜL: SAĞLIK SİGORTASI (TSS/ÖSS) ---
elif sayfa == "🏥 Sağlık (TSS/ÖSS)":
    st.title("🏥 Sağlık Sigortası Yapay Zeka Fiyatlama Robotu")
    st.markdown("Müşterinin fiziksel ve mesleki risk profilini çıkararak nokta atışı Tamamlayıcı (TSS) veya Özel (ÖSS) Sağlık Sigortası teklifi sunun.")
    st.markdown("---")
    
    s_col1, s_col2 = st.columns([1, 1.2], gap="large")
    
    with s_col1:
        s_musteri = st.text_input("Müşteri Adı Soyadı")
        s_tc_tel = st.text_input("T.C. Kimlik No (Sistem Kaydı İçin)", placeholder="Örn: 12345678901")
        s_tel = st.text_input("Telefon Numarası")
        
        st.markdown("### 📋 Profil Bilgileri")
        s_yas = st.slider("Yaş", min_value=18, max_value=80, value=30)
        c_boy, c_kilo = st.columns(2)
        s_boy = c_boy.number_input("Boy (cm)", min_value=140, max_value=220, value=175)
        s_kilo = c_kilo.number_input("Kilo (kg)", min_value=40, max_value=150, value=75)
        
        s_meslek = st.selectbox("Meslek / Çalışma Koşulu", ["Masa Başı / Ofis", "Sürekli Ayakta / Satış", "Ağır Sanayi / İnşaat", "Şoför / Lojistik", "Sağlık Çalışanı", "Çalışmıyor / Emekli"])
        s_hastalik = st.text_area("Mevcut/Geçmiş Hastalıklar (Varsa)", placeholder="Örn: Bel fıtığı, Hipertansiyon, Astım vb. Yoksa boş bırakın.")
        
        s_tip = st.radio("İstenen Poliçe Tipi", ["Tamamlayıcı Sağlık Sigortası (TSS)", "Özel Sağlık Sigortası (ÖSS)"], horizontal=True)

    with s_col2:
        # Vücut Kitle İndeksi (VKİ) Hesaplama
        vki = 0
        if s_boy > 0:
            boy_m = s_boy / 100
            vki = round(s_kilo / (boy_m * boy_m), 1)
        
        vki_durum = "Normal"
        if vki < 18.5: vki_durum = "Zayıf"
        elif vki > 25 and vki < 30: vki_durum = "Fazla Kilolu"
        elif vki >= 30: vki_durum = "Obez (Riskli)"
        
        st.info(f"⚖️ **Vücut Kitle İndeksi (VKİ): {vki} ({vki_durum})**")
        
        # Fiyat Hesaplama Algoritması
        taban_fiyat = 8000 if s_tip == "Tamamlayıcı Sağlık Sigortası (TSS)" else 25000
        yas_ek_primi = (s_yas - 18) * (150 if s_tip == "Tamamlayıcı Sağlık Sigortası (TSS)" else 400)
        vki_ek_primi = 3000 if vki >= 30 else 0
        hastalik_ek_primi = 5000 if len(s_hastalik) > 3 else 0
        
        toplam_saglik_primi = taban_fiyat + yas_ek_primi + vki_ek_primi + hastalik_ek_primi
        net_saglik_komisyonu = komisyon_hesapla(toplam_saglik_primi, s_tip)
        
        st.markdown(f"### 💰 Hesaplanan Toplam Prim: **{toplam_saglik_primi:,} TL**")
        
        # Yapay Zeka Risk Analizi Butonu
        if st.button("🧠 AI Risk Analizi Yap & Teminat Öner", type="primary", use_container_width=True):
            if s_musteri:
                with st.spinner("Gemini aktüeryal risk analizi yapıyor..."):
                    prompt = f"""Sen Grimset Studio'nun elit sağlık sigortası aktüerisin. Müşteri yaşı: {s_yas}, Boy: {s_boy}cm, Kilo: {s_kilo}kg (VKİ: {vki} - {vki_durum}), Meslek: {s_meslek}, Mevcut Hastalıklar: {s_hastalik if s_hastalik else 'Yok'}. 
Müşteriye {s_tip} poliçesi sunacağız. 
Lütfen şunları raporla:
1. **Risk Analizi:** Fiziksel ve mesleki durumuna göre olası sağlık riskleri nelerdir?
2. **Özel Teminat Önerisi:** Poliçeye hangi ek teminatlar (fizik tedavi, check-up, göz, diş vb.) kesinlikle eklenmeli?
3. **Satış Kapanış Cümlesi:** Satış temsilcisi (Ali) bu müşteriye telefonda tam olarak ne diyerek bu poliçeyi satmalı? (Çarpıcı ve ikna edici 2 cümle)"""
                    try:
                        analiz_sonucu = client.models.generate_content(model=TEXT_MODEL, contents=prompt).text
                        st.session_state.saglik_analizi = analiz_sonucu
                    except Exception as e: st.error("AI bağlantı hatası.")
            else:
                st.warning("Lütfen Müşteri Adını girin.")
                
        if "saglik_analizi" in st.session_state:
            with st.container(border=True):
                st.markdown("#### 🔬 Yapay Zeka Profil ve Satış Analizi")
                st.write(st.session_state.saglik_analizi)
        
        st.markdown("---")
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💾 Google Sheets'e Kaydet", use_container_width=True):
                if s_musteri and s_tc_tel and sh:
                    try:
                        zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        ai_ozet = st.session_state.saglik_analizi if "saglik_analizi" in st.session_state else "Standart Teminatlar"
                        
                        sh.worksheet("Üretilen Poliçeler").append_row([zaman, s_musteri, s_tc_tel, s_tip, "Yapay Zeka Özel Sağlık Analizi Eklidir", f"{toplam_saglik_primi:,} TL", st.session_state.kullanici_adi, f"{net_saglik_komisyonu:,} TL"])
                        try: sh.worksheet("Müşteri Portföyü").append_row([zaman, s_musteri, s_tel, s_tc_tel, "", f"Sağlık Profili: VKİ {vki}, Yaş {s_yas}"])
                        except: pass
                        st.success("Sağlık poliçesi sisteme işlendi!")
                    except Exception as e: st.error(f"Hata: {e}")
                else: st.warning("Müşteri Adı ve T.C. No girilmelidir.")
        
        with col_btn2:
            if s_musteri and s_tc_tel:
                ai_teminat_ozeti = f"Musteri Yasi: {s_yas}\nVucut Kitle Indeksi: {vki}\nMeslek Grubu: {s_meslek}\n\n* AI Tarafindan Belirlenen Ozel Kapsam onerileri ve Risk analizleri sisteme islenmistir."
                st.download_button("📄 PDF Teklif İndir", data=pdf_olustur(s_musteri, s_tc_tel, s_tip, ai_teminat_ozeti, f"{toplam_saglik_primi:,} TL"), file_name=f"Grimset_Saglik_{s_musteri.replace(' ','_')}.pdf", mime="application/pdf", use_container_width=True)

elif sayfa == "🏢 Kurumsal Filo (B2B)":
    st.title("🏢 Kurumsal Filo Yönetimi (B2B)")
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
                
                st.success(f"**{arac_sayisi} Adet Araç Eşleştirildi!**")
                st.info(f"İndirim: **%{int(indirim_orani*100)}** | Toplam Prim: **{toplam_filo_primi:,} TL**")
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

elif sayfa == "📌 Satış Hunisi (Kanban)":
    st.title("📌 Akıllı Satış Hunisi (Kanban Panosu)")
    st.markdown("---")
    if sh:
        try:
            ws_huni = sh.worksheet("Satış Hunisi")
            with st.expander("➕ Yeni Satış Fırsatı (Aday) Ekle"):
                with st.form("huni_form"):
                    h_isim = st.text_input("Müşteri Adı")
                    h_tel = st.text_input("Telefon")
                    h_konu = st.text_input("İlgilendiği Ürün")
                    gecmis_tutarlar = ["Belirtilmemiş"]
                    try:
                        policeler = sh.worksheet("Üretilen Poliçeler").get_all_records()
                        fiyatlar = set([str(p.get("Toplam Prim", "")) for p in policeler if "TL" in str(p.get("Toplam Prim", ""))])
                        def parse_fiyat(f):
                            try: return float(f.replace(" TL", "").replace(",", "").replace(".", ""))
                            except: return 0
                        gecmis_tutarlar.extend(sorted(list(fiyatlar), key=parse_fiyat))
                    except: pass
                    gecmis_tutarlar.append("Diğer (Manuel Gir)")
                    h_tutar_secim = st.selectbox("Tahmini Tutar", gecmis_tutarlar)
                    h_tutar_manuel = st.text_input("Özel Tutar Girin") if h_tutar_secim == "Diğer (Manuel Gir)" else ""
                    if st.form_submit_button("Adayı Huniye Ekle"):
                        if h_isim and h_konu:
                            zaman_id = datetime.now().strftime("%Y%m%d%H%M%S")
                            tarih = datetime.now().strftime("%Y-%m-%d")
                            final_tutar = h_tutar_manuel if h_tutar_secim == "Diğer (Manuel Gir)" else ("" if h_tutar_secim == "Belirtilmemiş" else h_tutar_secim)
                            ws_huni.append_row([zaman_id, tarih, h_isim, h_tel, h_konu, final_tutar, "Yeni Aday", st.session_state.kullanici_adi])
                            st.success(f"{h_isim} eklendi!")
                            st.rerun()
                        else: st.warning("İsim ve Ürün girin.")
            st.markdown("### 📊 Aktif Fırsatlar Tablosu")
            tum_veriler = ws_huni.get_all_values()
            if len(tum_veriler) > 1:
                satirlar = tum_veriler[1:]
                k1, k2, k3, k4 = st.columns(4)
                k1.markdown("<div style='background-color: #2980b9; padding: 10px; border-radius: 5px; text-align: center; color: white;'><b>🆕 Yeni Aday</b></div><br>", unsafe_allow_html=True)
                k2.markdown("<div style='background-color: #f39c12; padding: 10px; border-radius: 5px; text-align: center; color: white;'><b>⏳ Görüşülüyor</b></div><br>", unsafe_allow_html=True)
                k3.markdown("<div style='background-color: #8e44ad; padding: 10px; border-radius: 5px; text-align: center; color: white;'><b>📄 Teklif Verildi</b></div><br>", unsafe_allow_html=True)
                k4.markdown("<div style='background-color: #27ae60; padding: 10px; border-radius: 5px; text-align: center; color: white;'><b>🏆 Kazanıldı</b></div><br>", unsafe_allow_html=True)
                for idx, row in enumerate(satirlar):
                    if len(row) < 8: continue
                    r_id, r_tar, r_isim, r_tel, r_konu, r_tut, r_asama, r_sorumlu = row
                    hedef_kolon = k1 if r_asama=="Yeni Aday" else (k2 if r_asama=="Görüşülüyor" else (k3 if r_asama=="Teklif Verildi" else (k4 if r_asama=="Kazanıldı" else None)))
                    if not hedef_kolon: continue
                    with hedef_kolon:
                        with st.container(border=True):
                            st.markdown(f"**👤 {r_isim}**")
                            st.caption(f"🎯 Hedef: {r_konu}")
                            if r_tut: st.caption(f"💰 Tutar: {r_tut}")
                            st.caption(f"💼 Sorumlu: {r_sorumlu}")
                            secili_index = ["Yeni Aday", "Görüşülüyor", "Teklif Verildi", "Kazanıldı", "İptal Edildi"].index(r_asama) if r_asama in ["Yeni Aday", "Görüşülüyor", "Teklif Verildi", "Kazanıldı", "İptal Edildi"] else 0
                            yeni_asama = st.selectbox("Durumu Güncelle", ["Yeni Aday", "Görüşülüyor", "Teklif Verildi", "Kazanıldı", "İptal Edildi"], index=secili_index, key=f"asama_{r_id}")
                            if yeni_asama != r_asama:
                                ws_huni.update_cell(idx + 2, 7, yeni_asama)
                                st.rerun()
            else: st.info("Takip edilen fırsat yok.")
        except Exception as e: st.warning(f"Hata: {e}")

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
            </div>
            """, unsafe_allow_html=True)
            
            col1, col2, col3 = st.columns(3)
            col1.metric("💼 Toplam Kesilen Poliçe", f"{len(df)} Adet")
            col2.metric("📈 Toplam Üretim (Ciro)", f"{int(toplam_ciro):,} TL")
            col3.metric("🏆 En Çok Satılan", str(df['Poliçe Tipi'].mode()[0]))
            
            st.markdown("---")
            st.subheader("🏆 Satış Ekibi Liderlik Tablosu")
            satis_performansi = df.groupby('Satış Temsilcisi')['Net Komisyon'].sum().reset_index().sort_values(by='Net Komisyon', ascending=False)
            st.plotly_chart(px.bar(satis_performansi, x='Satış Temsilcisi', y='Net Komisyon', text_auto='.2s', color='Satış Temsilcisi'), use_container_width=True)
            
            st.markdown("---")
            g_col1, g_col2 = st.columns(2)
            with g_col1: st.plotly_chart(px.pie(df, names='Poliçe Tipi', values='Net Komisyon', hole=0.4, color_discrete_sequence=px.colors.sequential.Teal), use_container_width=True)
            with g_col2:
                df['Kısa Tarih'] = pd.to_datetime(df['Tarih']).dt.date
                st.plotly_chart(px.bar(df.groupby('Kısa Tarih')['Net Komisyon'].sum().reset_index(), x='Kısa Tarih', y='Net Komisyon', text_auto='.2s', color_discrete_sequence=['#4CAF50']), use_container_width=True)
            
            st.markdown("---")
            st.dataframe(df[['Tarih', 'Satış Temsilcisi', 'Müşteri Adı', 'Poliçe Tipi', 'Toplam Prim', 'Net Komisyon']].tail(10).iloc[::-1], use_container_width=True)
        except Exception as e: st.warning(f"Hata: {e}")
