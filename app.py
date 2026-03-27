import os, math, pickle, json, urllib.parse, smtplib, re
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

st.set_page_config(page_title="Grimset AI | Sigorta Otomasyonu", page_icon="🛡️", layout="wide")
st.markdown("""<style>.stButton>button { border-radius: 8px; transition: all 0.3s ease-in-out; font-weight: bold; } .stButton>button:hover { transform: scale(1.02); box-shadow: 0px 4px 15px rgba(0,0,0,0.1); } div[data-testid="metric-container"] { background-color: #1e1e1e; border: 1px solid #333; padding: 5% 5% 5% 10%; border-radius: 10px; box-shadow: 2px 2px 10px rgba(0,0,0,0.2); color: white; } [data-testid="stSidebar"] { background-color: #0e1117; border-right: 1px solid #2d2d2d; } .login-box { max-width: 400px; margin: auto; padding: 2rem; border-radius: 10px; background-color: #1e1e1e; box-shadow: 0 4px 8px rgba(0,0,0,0.2); } .status-badge { padding: 5px 10px; border-radius: 5px; font-weight: bold; color: white; display: inline-block; margin-bottom: 5px;} .otonom-card { background: linear-gradient(135deg, #2b5876 0%, #4e4376 100%); padding: 15px; border-radius: 10px; color: white; margin-bottom: 10px;} .mikro-card { background: linear-gradient(135deg, #ff9a9e 0%, #fecfef 99%, #fecfef 100%); padding: 15px; border-radius: 10px; color: #333; margin-bottom: 10px;}</style>""", unsafe_allow_html=True)

BELGELER_KLASORU, EVRAK_KASASI_KLASORU = "belgeler", "evrak_kasasi"
if not os.path.exists(BELGELER_KLASORU): os.makedirs(BELGELER_KLASORU)
if not os.path.exists(EVRAK_KASASI_KLASORU): os.makedirs(EVRAK_KASASI_KLASORU)

api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
if not api_key: st.error("API Anahtarı Eksik!"); st.stop()
client = genai.Client(api_key=api_key)
VISION_MODEL, TEXT_MODEL, HAFIZA_DOSYASI = 'gemini-2.5-flash', 'gemini-2.5-flash', "vektor_hafizasi.pkl"

@st.cache_resource
def sheets_baglantisi_kur():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        skey = json.loads(st.secrets["google_json"], strict=False)
        if "\\n" in skey.get("private_key", ""): skey["private_key"] = skey["private_key"].replace("\\n", "\n")
        gc = gspread.authorize(Credentials.from_service_account_info(skey, scopes=scopes))
        sh = gc.open("Grimset_CRM")
        for ws_name, cols in [("Müşteri Portföyü", ["Tarih", "Müşteri Adı", "Telefon", "Plaka", "Vade Tarihi", "OCR Detayı"]), ("Üretilen Poliçeler", ["Tarih", "Müşteri Adı", "Plaka", "Poliçe Tipi", "Teminatlar", "Toplam Prim", "Satış Temsilcisi", "Net Komisyon"]), ("Hasar Kayıtları", ["Tarih", "Müşteri Adı", "Plaka", "Hasar Raporu", "Durum"]), ("Filo Teklifleri", ["Tarih", "Firma Adı", "Araç Sayısı", "Plakalar", "Poliçe Tipi", "Toplam Prim", "Satış Temsilcisi", "Net Komisyon"]), ("Satış Hunisi", ["ID", "Tarih", "Müşteri Adı", "Telefon", "Konu", "Tahmini Tutar", "Aşama", "Sorumlu"]), ("Şirket Giderleri", ["Tarih", "Gider Kalemi", "Kategori", "Tutar", "Ekleyen"]), ("Evrak Kasası", ["Tarih", "Müşteri Adı", "Plaka", "Evrak Tipi", "Dosya Adı", "Ekleyen"]), ("Audit Log", ["Tarih", "Kullanıcı", "Rol", "İşlem Türü", "İşlem Detayı"]), ("B2B Talepler", ["Tarih", "Firma", "Personel Adı", "TC/Plaka", "Talep Tipi", "Durum"])]:
            try: sh.worksheet(ws_name)
            except: sh.add_worksheet(title=ws_name, rows="1000", cols="20").append_row(cols)
        return sh
    except Exception as e: st.error(f"Google Sheets Hatası: {e}"); return None

sh = sheets_baglantisi_kur()

def log_action(kullanici, rol, islem_turu, islem_detayi):
    if sh:
        try: sh.worksheet("Audit Log").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), kullanici, rol, islem_turu, islem_detayi])
        except: pass

if "giris_yapildi" not in st.session_state:
    st.session_state.update({"giris_yapildi": False, "rol": None, "kullanici_adi": None, "musteri_plaka": None, "musteri_tel": None, "firma_adi": None})

if not st.session_state.giris_yapildi:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown('<div class="login-box">', unsafe_allow_html=True)
        st.image("https://images.squarespace-cdn.com/content/v1/6055d01a61b2383be553b1b6/bd6d8e20-94d0-4e36-b552-6d2c4b574229/grimset+copy+copy+logo.png?format=1500w", width=200)
        st.markdown("<h3 style='text-align: center;'>Grimset Studio Sistem Girişi</h3>", unsafe_allow_html=True)
        # YENİ: B2B Giriş Sekmesi eklendi
        tab_personel, tab_musteri, tab_b2b = st.tabs(["🧑‍💼 Personel", "👤 Müşteri", "🏢 Kurumsal B2B"])
        with tab_personel:
            k_adi, sifre = st.text_input("Kullanıcı Adı", key="k_adi"), st.text_input("Şifre", type="password", key="sifre")
            if st.button("Giriş Yap", use_container_width=True, type="primary"):
                if k_adi == "admin" and sifre == "Grimset2026":
                    st.session_state.update({"giris_yapildi": True, "rol": "Admin", "kullanici_adi": "Yönetici"})
                    log_action("Yönetici", "Admin", "Sisteme Giriş", "Başarılı")
                    st.rerun()
                elif k_adi == "ali" and sifre == "satis123":
                    st.session_state.update({"giris_yapildi": True, "rol": "Satis", "kullanici_adi": "Ali"})
                    log_action("Ali", "Satis", "Sisteme Giriş", "Başarılı")
                    st.rerun()
                else: st.error("Hatalı giriş!")
        with tab_musteri:
            m_plaka_giris, m_tel_giris = st.text_input("Plaka veya T.C. No", placeholder="Örn: 34ABC123"), st.text_input("Sisteme Kayıtlı Telefon", type="password")
            if st.button("Müşteri Paneline Gir", use_container_width=True, type="primary"):
                if sh and m_plaka_giris and m_tel_giris:
                    try:
                        giris_basarili = False
                        p_in, t_in = m_plaka_giris.replace(" ", "").upper(), m_tel_giris.replace(" ", "")
                        for m in sh.worksheet("Müşteri Portföyü").get_all_records():
                            if str(m.get("Plaka", "")).replace(" ", "").upper() == p_in and str(m.get("Telefon", "")).replace(" ", "") == t_in:
                                st.session_state.update({"giris_yapildi": True, "rol": "Musteri", "kullanici_adi": str(m.get("Müşteri Adı", "Müşteri")), "musteri_plaka": p_in, "musteri_tel": t_in})
                                giris_basarili = True
                                log_action(st.session_state.kullanici_adi, "Musteri", "Müşteri Girişi", f"Plaka/TC: {p_in}")
                                st.rerun(); break
                        if not giris_basarili: st.error("Kayıt bulunamadı.")
                    except Exception as e: st.error("Hata.")
                else: st.warning("Bilgileri girin.")
        with tab_b2b:
            st.info("Kurumsal İK veya Filo yöneticisi girişi.")
            b2b_kod = st.text_input("Firma Kodu", placeholder="Örn: TECH100")
            b2b_sifre = st.text_input("Firma Şifresi", type="password")
            if st.button("Kurumsal Giriş", use_container_width=True, type="primary"):
                # Demo B2B Firması: Tech A.Ş.
                if b2b_kod == "TECH100" and b2b_sifre == "b2b123":
                    st.session_state.update({"giris_yapildi": True, "rol": "B2B_IK", "kullanici_adi": "Tech A.Ş. İK Müdürü", "firma_adi": "Tech A.Ş."})
                    log_action("Tech A.Ş.", "B2B", "Kurumsal Giriş", "Başarılı")
                    st.rerun()
                else: st.error("Geçersiz firma kodu veya şifre.")
        st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# --- Helper Functions (Minified) ---
def metni_vektore_cevir(metin): return client.models.embed_content(model='gemini-embedding-001', contents=metin).embeddings[0].values
def benzerlik_hesapla(v1, v2):
    mag1, mag2 = math.sqrt(sum(a*a for a in v1)), math.sqrt(sum(a*a for a in v2))
    return sum(a*b for a,b in zip(v1,v2)) / (mag1*mag2) if mag1*mag2 != 0 else 0
@st.cache_resource
def veritabani_yukle():
    if os.path.exists(HAFIZA_DOSYASI): return pickle.load(open(HAFIZA_DOSYASI, 'rb'))
    docs = [f for f in os.listdir(BELGELER_KLASORU) if f.endswith('.pdf')]
    txt = "".join([f"\n[Kaynak: {d}]\n" + p.extract_text() for d in docs for p in PdfReader(os.path.join(BELGELER_KLASORU, d)).pages if p.extract_text()])
    db = [{"metin": p, "vektor": metni_vektore_cevir(p)} for p in [txt[i:i+1000] for i in range(0, len(txt), 1000)] if len(p.strip())>50]
    pickle.dump(db, open(HAFIZA_DOSYASI, 'wb')); return db
def coklu_belge_oku(dosyalar):
    try: return client.models.generate_content(model=VISION_MODEL, contents=["Belgeleri analiz et. İsim, TC, Plaka çıkar."] + [Image.open(d) for d in dosyalar]).text
    except Exception as e: return f"Hata: {e}"
def kaza_analizi_yap(dosyalar, plaka, isim, beyan="Belirtilmedi"):
    try: return client.models.generate_content(model=VISION_MODEL, contents=[f"Eksper raporu. Müşteri: {isim}, Araç: {plaka}. Beyan: '{beyan}'. 1.Hasar Analizi, 2.Kusur, 3.Suistimal (Fraud) İhtimali (% olarak sert dille), 4.Dilekçe."] + [Image.open(d) for d in dosyalar]).text
    except Exception as e: return f"Hata: {e}"
def kvkk_pdf_olustur(isim, plaka):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 14); pdf.cell(0, 10, "GRIMSET STUDIO", ln=True, align="C"); pdf.set_font("Arial", "B", 12); pdf.cell(0, 10, "KVKK AYDINLATMA METNI", ln=True, align="C"); pdf.set_font("Arial", "", 10); pdf.multi_cell(0, 7, f"Sayin {isim} ({plaka}),\nVerileriniz KVKK kapsaminda sigorta islemleri icin islenmektedir. Bu belgeye 'ONAYLIYORUM' demeniz acik riza sayilir."); return pdf.output(dest="S").encode("latin-1")
def pdf_olustur(isim, plaka, tip, tem, prim, piyasa=None, kazanc=None, ref=None, dil="Türkçe"):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 16); pdf.cell(0, 10, f"GRIMSET STUDIO - QUOTE ({dil})", ln=True, align="C"); pdf.set_font("Arial", "", 12); pdf.cell(0, 10, f"Client: {isim}", ln=True); pdf.cell(0, 10, f"ID/Plate: {plaka}", ln=True); pdf.cell(0, 10, f"Type: {tip}", ln=True); pdf.multi_cell(0, 8, f"Details:\n{tem}"); pdf.set_font("Arial", "B", 14); pdf.cell(0, 10, f"Premium: {prim}", ln=True); return pdf.output(dest="S").encode("latin-1")
def komisyon_hesapla(prim, tip):
    oran = 0.25 if tip in ["Seyahat Sağlık (Yurt Dışı)", "Elektronik Cihaz (Telefon/Laptop)", "Evcil Hayvan (Pati) Acil Durum", "Kısa Süreli Kiralık Araç Kaskosu"] else (0.15 if tip in ["Kasko", "Filo Kasko", "DASK", "Tamamlayıcı Sağlık Sigortası (TSS)", "Özel Sağlık Sigortası (ÖSS)"] else 0.08 if "Trafik" in tip else 0.10)
    return int(prim * oran)
def get_status_color(d): return {"İnceleniyor": "#f39c12", "Eksper Atandı": "#3498db", "Onarımda": "#9b59b6", "Ödeme Bekleniyor": "#e67e22", "Tamamlandı": "#2ecc71", "Bekliyor": "#e74c3c", "Onaylandı": "#2ecc71"}.get(d, "#95a5a6")
def temizle_fiyat(x):
    try: return int(str(x).replace(' TL', '').replace(',', '').replace('.', ''))
    except: return 0

db = veritabani_yukle()

# --- YAN MENÜ ---
st.sidebar.image("https://images.squarespace-cdn.com/content/v1/6055d01a61b2383be553b1b6/bd6d8e20-94d0-4e36-b552-6d2c4b574229/grimset+copy+copy+logo.png?format=1500w", width=150)
st.sidebar.markdown(f"**👤 Kullanıcı:** {st.session_state.kullanici_adi}")
if st.sidebar.button("🚪 Çıkış", use_container_width=True): log_action(st.session_state.kullanici_adi, st.session_state.rol, "Çıkış", ""); st.session_state.giris_yapildi=False; st.rerun()

if st.session_state.rol in ["Admin", "Satis"]:
    st.sidebar.title("Modüller")
    menu_secenekleri = [
        "📋 Kayıt & Ayıklama", 
        "📝 Poliçe Atölyesi", 
        "⏱️ Mikro Sigorta (On-Demand)",
        "🏥 Sağlık (TSS/ÖSS)", 
        "🏢 Kurumsal Filo (B2B)", 
        "⏰ Vade & Otonom Yenileme", 
        "📌 Satış Hunisi (Kanban)", 
        "📅 Ajanda & Randevu", 
        "🚗 Hasar Asistanı & Süreç Yönetimi", 
        "🗄️ Dijital Evrak Kasası", 
        "⚖️ Karşılaştırma",
        "🎫 Müşteri Destek Masası",
        "📡 Telematik (Sürüş Analizi)" # YENİ EKLENDİ
    ]
    if st.session_state.rol == "Admin":
        menu_secenekleri.extend([
            "🎯 Kampanya Motoru", 
            "📈 LTV & Churn Analizi", 
            "💸 Gider Yönetimi", 
            "📊 Finansal & Coğrafi Dashboard",
            "🔐 Denetim İzi (Audit Log)",
            "🌐 Developer API & Entegrasyon"
        ])
    sayfa = st.sidebar.radio("İşlem Seçin:", menu_secenekleri)
elif st.session_state.rol == "B2B_IK":
    sayfa = st.sidebar.radio("Menü:", ["🏢 Şirket Özeti & Talepler", "🧑‍🤝‍🧑 Personel Poliçeleri"])
else:
    st.sidebar.title("Müşteri Paneli")
    menu_secenekleri = ["🏠 Poliçelerim", "⏱️ Mikro Sigorta Al", "🚗 Hasar Bildir & Takip Et", "🗄️ Evrak Kasam", "🎫 Destek Talebi (Ticket)"] # YENİ EKLENDİ
    sayfa = st.sidebar.radio("İşlem Seçin:", menu_secenekleri)

st.sidebar.markdown("---")
st.sidebar.caption("Grimset Studio © 2026")

# --- KURUMSAL B2B (İK) EKRANLARI ---
if sayfa == "🏢 Şirket Özeti & Talepler" and st.session_state.rol == "B2B_IK":
    st.title(f"🏢 {st.session_state.firma_adi} - İnsan Kaynakları Paneli")
    st.markdown("Şirketinize ait personel sağlık (TSS/ÖSS) ve filo kasko işlemlerini buradan yönetebilirsiniz.")
    st.markdown("---")
    
    b2b_c1, b2b_c2 = st.columns([1, 1.5], gap="large")
    with b2b_c1:
        st.subheader("➕ Yeni Personel Sigorta Talebi")
        with st.form("b2b_talep_form"):
            per_ad = st.text_input("Personel Adı Soyadı")
            per_tc = st.text_input("Personel T.C. Kimlik No")
            talep_tip = st.selectbox("Talep Edilen Güvence", ["Tamamlayıcı Sağlık Sigortası (TSS)", "Özel Sağlık Sigortası (ÖSS)", "Şirket Aracı Kaskosu"])
            if st.form_submit_button("Talebi Grimset'e İlet", type="primary"):
                if per_ad and per_tc and sh:
                    try:
                        sh.worksheet("B2B Talepler").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state.firma_adi, per_ad, per_tc, talep_tip, "Bekliyor"])
                        log_action(st.session_state.kullanici_adi, "B2B", "Yeni Personel Talebi", f"Personel: {per_ad}")
                        st.success("Talebiniz acenteye iletildi! İşlem sağlandığında durum güncellenecektir.")
                        st.rerun()
                    except Exception as e: st.error(f"Hata: {e}")
                else: st.warning("Bilgileri doldurunuz.")
                
    with b2b_c2:
        st.subheader("📋 Güncel Taleplerinizin Durumu")
        if sh:
            try:
                talepler = sh.worksheet("B2B Talepler").get_all_records()
                bizim_talepler = [t for t in talepler if t.get("Firma") == st.session_state.firma_adi]
                if not bizim_talepler: st.info("Henüz oluşturulmuş bir talebiniz bulunmuyor.")
                else:
                    for t in reversed(bizim_talepler):
                        durum = t.get("Durum", "Bekliyor")
                        renk = get_status_color(durum)
                        with st.container(border=True):
                            st.markdown(f"**Personel:** {t.get('Personel Adı')} | **Talep:** {t.get('Talep Tipi')}")
                            st.markdown(f"Tarih: {t.get('Tarih')} | <span class='status-badge' style='background-color:{renk}'>{durum}</span>", unsafe_allow_html=True)
            except Exception as e: st.error("Veri hatası.")

elif sayfa == "🧑‍🤝‍🧑 Personel Poliçeleri" and st.session_state.rol == "B2B_IK":
    st.title("🧑‍🤝‍🧑 Şirket Personeli Aktif Poliçeler")
    st.info("Bu ekran ilerleyen güncellemelerde devreye alınacaktır. Tüm personel PDF'lerinizi buradan indirebileceksiniz.")

# --- MÜŞTERİ EKRANLARI ---
elif sayfa == "🏠 Poliçelerim" and st.session_state.rol == "Musteri":
    st.title("👋 Poliçelerim")
    if sh:
        pols = [p for p in sh.worksheet("Üretilen Poliçeler").get_all_records() if str(p.get("Plaka")).upper() == st.session_state.musteri_plaka]
        for p in pols:
            with st.container():
                st.subheader(p.get('Poliçe Tipi', ''))
                st.write(f"Tarih: {p.get('Tarih','')} | Prim: {p.get('Toplam Prim','')} \n\nTeminat: {p.get('Teminatlar','')}")
                st.markdown("---")

elif sayfa == "⏱️ Mikro Sigorta Al" and st.session_state.rol == "Musteri":
    st.title("⏱️ Mikro Sigorta")
    uf = {"Seyahat Sağlık (Yurt Dışı)": 60, "Elektronik Cihaz (Telefon/Laptop)": 35, "Evcil Hayvan (Pati) Acil Durum": 25, "Kısa Süreli Kiralık Araç Kaskosu": 150}
    urun = st.selectbox("Koruma:", list(uf.keys()))
    gun = st.slider("Gün:", 1, 30, 3)
    detay = st.text_input("Detay (IMEI/Pasaport)")
    tf = uf[urun] * gun
    st.info(f"**Toplam Tutar: {tf} TL**")
    if st.button("💳 Kredi Kartı İle Öde", type="primary"):
        if detay and sh:
            zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sh.worksheet("Üretilen Poliçeler").append_row([zaman, st.session_state.kullanici_adi, st.session_state.musteri_plaka, urun, f"Sure:{gun}, Detay:{detay}", f"{tf} TL", "Self-Servis", f"{komisyon_hesapla(tf, urun)} TL"])
            log_action(st.session_state.kullanici_adi, "Musteri", "Mikro Alım", urun)
            st.success("Poliçeniz kesildi!")

elif sayfa == "🚗 Hasar Bildir & Takip" and st.session_state.rol == "Musteri":
    st.title("🚗 Hasar Takip")
    if sh:
        hlar = [h for h in sh.worksheet("Hasar Kayıtları").get_all_records() if str(h.get("Plaka")).upper() == st.session_state.musteri_plaka]
        for h in hlar:
            st.markdown(f"<span class='status-badge' style='background-color:{get_status_color(str(h.get('Durum')))}'>Durum: {h.get('Durum')}</span> - {h.get('Tarih')}", unsafe_allow_html=True)
    st.markdown("### Yeni Hasar Bildir (AI)")
    beyan = st.text_area("Kaza senaryosu")
    fotolar = st.file_uploader("Fotoğraflar", accept_multiple_files=True, type=["jpg","png"])
    if st.button("Raporla"):
        if beyan and fotolar:
            analiz = kaza_analizi_yap(fotolar, st.session_state.musteri_plaka, st.session_state.kullanici_adi, beyan)
            st.info(analiz)
            sh.worksheet("Hasar Kayıtları").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state.kullanici_adi, st.session_state.musteri_plaka, analiz, "İnceleniyor"])
            st.success("Kaydedildi.")

elif sayfa == "🗄️ Evrak Kasam" and st.session_state.rol == "Musteri":
    st.title("🗄️ Evrak Kasam")
    if sh:
        evraklar = [e for e in sh.worksheet("Evrak Kasası").get_all_records() if str(e.get("Plaka")).upper() == st.session_state.musteri_plaka]
        for e in evraklar: st.write(f"📑 {e.get('Evrak Tipi')} - {e.get('Dosya Adı')}")

# --- PERSONEL EKRANLARI ---
elif sayfa == "📋 Kayıt & Ayıklama":
    st.title("🛡️ Müşteri Kayıt & KVKK")
    with st.form("kayit"):
        isim, tel, plaka, vade = st.text_input("Ad"), st.text_input("Tel"), st.text_input("Plaka/TC"), st.date_input("Vade")
        if st.form_submit_button("Kaydet") and isim and plaka and sh:
            sh.worksheet("Müşteri Portföyü").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), isim, tel, plaka, str(vade), "Manuel"])
            st.session_state.update({"son_isim": isim, "son_tel": tel, "son_plaka": plaka})
            st.success("Eklendi.")
    if st.session_state.get("son_isim"):
        st.success("KVKK Metnini müşteriye onaya sunun.")
        st.markdown(f'<a href="https://wa.me/90{st.session_state.son_tel.replace(" ","")[-10:]}?text=KVKK onayiniz icin ONAYLIYORUM yazin."><div style="background:#25D366;color:white;padding:10px;text-align:center;border-radius:5px;">📲 WhatsApp Onay İste</div></a>', unsafe_allow_html=True)

elif sayfa == "📝 Poliçe Atölyesi":
    st.title("📝 Poliçe Atölyesi (Dinamik Rayiç & Global)")
    st.markdown("---")
    secilen_dil = st.radio("🌍 Müşteri İletişim Dili (PDF ve Mesaj Şablonu)", ["Türkçe", "English", "Deutsch", "Français"], horizontal=True)
    
    dinamik_fiyat = st.toggle("📊 Mikroekonomik Dinamik Fiyatlama (Görünmez El) Aktif Et", value=True)
    st.markdown("---")
    
    col1, col2 = st.columns([1, 1], gap="large")
    with col1:
        p_musteri = st.text_input("Müşteri Adı Soyadı")
        p_tel = st.text_input("Telefon (WhatsApp için)")
        p_plaka = st.text_input("Araç Plakası veya Adres Kodu (DASK)")
        p_tip = st.selectbox("Poliçe Tipi", ["Kasko", "Zorunlu Trafik Sigortası", "DASK"])
        
        # YENİ: DİNAMİK KASKO DEĞER MOTORU (ARAÇ BİLGİLERİ)
        st.markdown("##### 🚙 Araç Değer & Rayiç Bilgileri")
        c_arac1, c_arac2 = st.columns(2)
        p_marka = c_arac1.selectbox("Araç Markası Segmenti", ["Ekonomi (Fiat, Renault, Dacia)", "Orta Sınıf (VW, Toyota, Honda)", "Premium (Mercedes, BMW, Audi)", "Lüks Spor (Porsche, Land Rover)"])
        p_yil = c_arac2.slider("Model Yılı", min_value=2005, max_value=2026, value=2020)
        
        teminat_cam = st.checkbox("Sınırsız Orijinal Cam Değişimi", value=True)
        teminat_ikame = st.selectbox("İkame Araç Süresi", ["Yılda 2 Kez, 15 Gün", "Yılda 2 Kez, 7 Gün", "İkame Araç Yok"])
        teminat_imm = st.select_slider("İMM Limiti", options=["1.000.000 TL", "5.000.000 TL", "Sınırsız"], value="5.000.000 TL")
        st.markdown("---")
        kullanilan_ref = st.text_input("Müşteri bir kod getirdi mi?", placeholder="Örn: MEHMET-123 (Opsiyonel)")
        
    with col2:
        # YENİ: RAYİÇ BEDEL HESAPLAMA MOTORU
        arac_rayic_bedeli = 500000 # Default
        if "Ekonomi" in p_marka: arac_rayic_bedeli = 800000 + ((p_yil - 2005) * 40000)
        elif "Orta Sınıf" in p_marka: arac_rayic_bedeli = 1200000 + ((p_yil - 2005) * 60000)
        elif "Premium" in p_marka: arac_rayic_bedeli = 3000000 + ((p_yil - 2005) * 150000)
        elif "Lüks Spor" in p_marka: arac_rayic_bedeli = 6000000 + ((p_yil - 2005) * 300000)
        
        # 1. Taban Fiyat Hesaplama (Kasko ise Rayiç bedel üzerinden %1.5 risk payı alırız)
        kasko_primi = int(arac_rayic_bedeli * 0.015) if p_tip == "Kasko" else 0
        trafik_primi = 8500 if p_tip == "Zorunlu Trafik Sigortası" else 0
        dask_primi = 1200 if p_tip == "DASK" else 0
        
        taban_prim = kasko_primi + trafik_primi + dask_primi + (1200 if teminat_cam and p_tip == "Kasko" else 0) + (3000 if teminat_imm=="Sınırsız" and p_tip in ["Kasko", "Zorunlu Trafik Sigortası"] else 0)
        
        piyasa_primi = int(taban_prim * 1.18)
        tahmini_prim = taban_prim
        dinamik_mesaj = ""
        
        # Dinamik Fiyatlama ve LTV Algoritması
        if dinamik_fiyat and p_musteri and sh:
            try:
                policeler = sh.worksheet("Üretilen Poliçeler").get_all_records()
                df_pol = pd.DataFrame(policeler)
                islem_sayisi = len(df_pol[df_pol['Müşteri Adı'].astype(str).str.upper() == p_musteri.upper()]) if not df_pol.empty and 'Müşteri Adı' in df_pol.columns else 0
                
                if islem_sayisi >= 2:
                    indirim_tutari = int(tahmini_prim * 0.08)
                    tahmini_prim -= indirim_tutari
                    dinamik_mesaj = f"📉 **Dinamik Fiyatlama (LTV Etkisi):** {islem_sayisi} geçmiş işlem. Sadakati korumak için **-{indirim_tutari:,} TL** VIP indirimi uygulandı."
                elif islem_sayisi == 0:
                    indirim_tutari = int(tahmini_prim * 0.03)
                    tahmini_prim -= indirim_tutari
                    dinamik_mesaj = f"📈 **Dinamik Fiyatlama (Penetrasyon):** Yeni müşteri. Pazara sızma stratejisiyle **-{indirim_tutari:,} TL** rekabetçi indirim yapıldı."
                else:
                    dinamik_mesaj = "⚖️ **Dinamik Fiyatlama:** Standart risk algoritması devrede."
            except: pass

        if kullanilan_ref:
            ref_indirim = int(tahmini_prim * 0.05)
            tahmini_prim -= ref_indirim
            st.success(f"🎉 Referans İndirimi Uygulandı: -{ref_indirim:,} TL")
            
        avantaj_tutari = piyasa_primi - tahmini_prim
        net_komisyon_tutari = komisyon_hesapla(tahmini_prim, p_tip)
        
        prim_yazisi = f"{tahmini_prim:,} TL"
        piyasa_yazisi = f"{piyasa_primi:,} TL"
        avantaj_yazisi = f"{avantaj_tutari:,} TL"
        net_komisyon_yazisi = f"{net_komisyon_tutari:,} TL"
        
        musteri_ozel_ref_kodu = f"{p_musteri.split()[0].upper().replace(' ', '')}-{p_plaka[-3:].upper() if len(p_plaka)>=3 else 'GRM'}" if p_musteri and p_plaka else ""
        
        if p_tip == "Kasko":
            st.info(f"🚙 **Sistem Tarafından Belirlenen Araç Rayiç Bedeli:** {arac_rayic_bedeli:,} TL")
        st.info("📊 **Fiyat & Rekabet Analizi**")
        
        if dinamik_mesaj: st.caption(dinamik_mesaj)
            
        c_m1, c_m2 = st.columns(2)
        c_m1.metric("Grimset Özel Fiyatı", prim_yazisi)
        c_m2.metric("Müşterinin Kazancı", avantaj_yazisi, delta=f"-{avantaj_tutari:,} TL Fark", delta_color="inverse")
        
        cam_text = "Sınırsız" if teminat_cam else "Muafiyetli"
        teminat_ozeti = f"- Cam: {cam_text}\n- İkame: {teminat_ikame}\n- İMM: {teminat_imm}"
        if p_tip == "Kasko": teminat_ozeti = f"- Araç Grubu: {p_marka.split(' ')[0]} ({p_yil})\n" + teminat_ozeti
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
                        try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Poliçe Kesildi (Rayiçli)", f"Müşteri: {p_musteri}, Tutar: {prim_yazisi}")
                        except: pass
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
                wp_mesaj = f"Hello {p_musteri},\nYour {p_tip} quote for {p_plaka} by Grimset Studio is ready.\n\nMarket Average: {piyasa_yazisi}\n*Grimset Discounted Price:* {prim_yazisi}\nYour total savings: {avantaj_yazisi}!\n\n🎁 EXCLUSIVE AFFILIATE CODE: {musteri_ozel_ref_kodu}\nShare this code with friends for a 10% discount on your next renewal!"
            else:
                wp_mesaj = f"Merhaba {p_musteri},\nGrimset Studio güvencesiyle {p_plaka} plakalı aracınız için {p_tip} teklifiniz hazırlanmıştır.\n\nPiyasa Ortalaması: {piyasa_yazisi}\n*İndirimli Tutar:* {prim_yazisi}\nKazancınız: {avantaj_yazisi}!\n\n🎁 REFERANS KODUNUZ: {musteri_ozel_ref_kodu}\nBu kodu arkadaşlarınızla paylaşarak %10 İNDİRİM kazanın!"
                
            wa_link = f"https://wa.me/90{p_tel.replace(' ', '').replace('+90', '').replace('0', '', 1)}?text={urllib.parse.quote(wp_mesaj)}" if p_tel else f"https://wa.me/?text={urllib.parse.quote(wp_mesaj)}"
            st.markdown(f'<a href="{wa_link}" target="_blank" style="text-decoration: none;"><div style="background-color: #25D366; color: white; text-align: center; padding: 10px; border-radius: 8px; font-weight: bold; margin-bottom: 10px;">💬 WhatsApp Gönder</div></a>', unsafe_allow_html=True)

elif sayfa == "⏱️ Mikro Sigorta (On-Demand)":
    st.title("⏱️ Anlık & Kısa Süreli Mikro Sigorta Satışı")
    st.markdown("Müşterilere telefon veya stant üzerinden hızlıca kullan-at (Pay-As-You-Go) poliçe satın. Sürümden kazanın!")
    st.markdown("---")
    m_col1, m_col2 = st.columns([1, 1], gap="large")
    with m_col1:
        p_musteri = st.text_input("Müşteri Adı Soyadı")
        p_tc_plaka = st.text_input("T.C. No veya Plaka")
        p_tel = st.text_input("Telefon (WhatsApp İçin)")
        st.markdown("---")
        urun_fiyatlari = {"Seyahat Sağlık (Yurt Dışı)": 60, "Elektronik Cihaz (Telefon/Laptop)": 35, "Evcil Hayvan (Pati) Acil Durum": 25, "Kısa Süreli Kiralık Araç Kaskosu": 150}
        m_urun = st.selectbox("Koruma Altına Alınacak Konu:", list(urun_fiyatlari.keys()))
        m_gun = st.slider("Kaç Günlük Güvence İstiyorsunuz?", min_value=1, max_value=30, value=3)
        m_detay = st.text_input("Gerekli Detay (Pasaport No, Cihaz IMEI, Çip No vb.)")
    with m_col2:
        gunluk_fiyat = urun_fiyatlari[m_urun]
        toplam_fiyat = gunluk_fiyat * m_gun
        komisyon = komisyon_hesapla(toplam_fiyat, m_urun)
        st.markdown(f"""<div class="mikro-card"><h4>Seçilen Paket: {m_urun}</h4><p>Süre: <b>{m_gun} Gün</b></p><h2 style="color: #d81b60;">Toplam: {toplam_fiyat} TL</h2><p style="font-size: 0.9rem; color: #555;"><i>Grimset Net Komisyon (%25): +{komisyon} TL</i></p></div>""", unsafe_allow_html=True)
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("💳 Tahsil Et & Sisteme İşle", type="primary", use_container_width=True):
                if p_musteri and p_tc_plaka and m_detay and sh:
                    with st.spinner("Poliçe kaydediliyor..."):
                        zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        teminat_ozeti = f"Sure: {m_gun} Gun\nKapsam Tipi: Kullan-At (On-Demand)\nDetay/ID: {m_detay}"
                        try:
                            sh.worksheet("Üretilen Poliçeler").append_row([zaman, p_musteri, p_tc_plaka, m_urun, teminat_ozeti, f"{toplam_fiyat} TL", st.session_state.kullanici_adi, f"{komisyon} TL"])
                            pdf_bytes = pdf_olustur(p_musteri, p_tc_plaka, m_urun, teminat_ozeti, f"{toplam_fiyat} TL")
                            dosya_adi = f"{p_tc_plaka}_{datetime.now().strftime('%Y%m%d%H%M%S')}_MikroPolice.pdf"
                            dosya_yolu = os.path.join(EVRAK_KASASI_KLASORU, dosya_adi)
                            with open(dosya_yolu, "wb") as f: f.write(pdf_bytes)
                            sh.worksheet("Evrak Kasası").append_row([zaman, p_musteri, p_tc_plaka, "Mikro Poliçe", dosya_adi, st.session_state.kullanici_adi])
                            try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Mikro Sigorta Satışı", f"Ürün: {m_urun}, Tutar: {toplam_fiyat} TL")
                            except: pass
                            try: sh.worksheet("Müşteri Portföyü").append_row([zaman, p_musteri, p_tel, p_tc_plaka, "", "Mikro Sigorta"])
                            except: pass
                            st.success("✅ Poliçe kesildi ve müşterinin evrak kasasına arşivlendi!")
                        except Exception as e: st.error(f"Hata oluştu: {e}")
                else: st.warning("Müşteri adı, TC/Plaka ve IMEI/Pasaport detayı zorunludur.")
        with col_btn2:
            if p_musteri and p_tc_plaka and m_detay:
                teminat_ozeti = f"Sure: {m_gun} Gun\nKapsam Tipi: Kullan-At (On-Demand)\nDetay/ID: {m_detay}"
                st.download_button("📄 PDF İndir", data=pdf_olustur(p_musteri, p_tc_plaka, m_urun, teminat_ozeti, f"{toplam_fiyat} TL"), file_name=f"Grimset_Mikro_{p_tc_plaka}.pdf", mime="application/pdf", use_container_width=True)

elif sayfa == "🏥 Sağlık (TSS/ÖSS)":
    st.title("🏥 Sağlık Sigortası Yapay Zeka Fiyatlama Robotu")
    st.markdown("---")
    s_col1, s_col2 = st.columns([1, 1.2], gap="large")
    with s_col1:
        s_musteri = st.text_input("Müşteri Adı Soyadı")
        s_tc_tel = st.text_input("T.C. Kimlik No", placeholder="Örn: 12345678901")
        s_tel = st.text_input("Telefon Numarası")
        st.markdown("### 📋 Profil Bilgileri")
        s_yas = st.slider("Yaş", min_value=18, max_value=80, value=30)
        c_boy, c_kilo = st.columns(2)
        s_boy = c_boy.number_input("Boy (cm)", min_value=140, max_value=220, value=175)
        s_kilo = c_kilo.number_input("Kilo (kg)", min_value=40, max_value=150, value=75)
        s_meslek = st.selectbox("Meslek / Çalışma Koşulu", ["Masa Başı / Ofis", "Sürekli Ayakta / Satış", "Ağır Sanayi / İnşaat", "Şoför / Lojistik", "Sağlık Çalışanı", "Çalışmıyor / Emekli"])
        s_hastalik = st.text_area("Mevcut/Geçmiş Hastalıklar", placeholder="Örn: Bel fıtığı, Hipertansiyon, Astım vb.")
        s_tip = st.radio("İstenen Poliçe Tipi", ["Tamamlayıcı Sağlık Sigortası (TSS)", "Özel Sağlık Sigortası (ÖSS)"], horizontal=True)

    with s_col2:
        vki = round(s_kilo / ((s_boy / 100) ** 2), 1) if s_boy > 0 else 0
        vki_durum = "Normal"
        if vki < 18.5: vki_durum = "Zayıf"
        elif vki > 25 and vki < 30: vki_durum = "Fazla Kilolu"
        elif vki >= 30: vki_durum = "Obez (Riskli)"
        st.info(f"⚖️ **Vücut Kitle İndeksi (VKİ): {vki} ({vki_durum})**")
        
        taban_fiyat = 8000 if s_tip == "Tamamlayıcı Sağlık Sigortası (TSS)" else 25000
        yas_ek_primi = (s_yas - 18) * (150 if s_tip == "Tamamlayıcı Sağlık Sigortası (TSS)" else 400)
        vki_ek_primi = 3000 if vki >= 30 else 0
        hastalik_ek_primi = 5000 if len(s_hastalik) > 3 else 0
        toplam_saglik_primi = taban_fiyat + yas_ek_primi + vki_ek_primi + hastalik_ek_primi
        net_saglik_komisyonu = komisyon_hesapla(toplam_saglik_primi, s_tip)
        st.markdown(f"### 💰 Hesaplanan Toplam Prim: **{toplam_saglik_primi:,} TL**")
        
        if st.button("🧠 AI Risk Analizi Yap & Teminat Öner", type="primary", use_container_width=True):
            if s_musteri:
                with st.spinner("Gemini aktüeryal risk analizi yapıyor..."):
                    prompt = f"Sen elit sağlık aktüerisin. Müşteri yaşı: {s_yas}, VKİ: {vki_durum}, Meslek: {s_meslek}, Hastalıklar: {s_hastalik if s_hastalik else 'Yok'}. 1. Olası riskler, 2. Önerilen ek teminatlar, 3. Satış kapanış cümlesi (2 cümle)."
                    try: st.session_state.saglik_analizi = client.models.generate_content(model=TEXT_MODEL, contents=prompt).text
                    except Exception as e: st.error("AI bağlantı hatası.")
            else: st.warning("Lütfen Müşteri Adını girin.")
                
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
                        sh.worksheet("Üretilen Poliçeler").append_row([zaman, s_musteri, s_tc_tel, s_tip, "Yapay Zeka Özel Sağlık Analizi Eklidir", f"{toplam_saglik_primi:,} TL", st.session_state.kullanici_adi, f"{net_saglik_komisyonu:,} TL"])
                        try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Sağlık Poliçesi Üretimi", f"Tipi: {s_tip}, Müşteri: {s_musteri}")
                        except: pass
                        st.success("Sağlık poliçesi sisteme işlendi!")
                    except Exception as e: st.error(f"Hata: {e}")
        with col_btn2:
            if s_musteri and s_tc_tel:
                ai_teminat_ozeti = f"Musteri Yasi: {s_yas}\nVucut Kitle Indeksi: {vki}\nMeslek Grubu: {s_meslek}\n\n* AI Tarafindan Belirlenen Ozel Kapsam onerileri ve Risk analizleri sisteme islenmistir."
                st.download_button("📄 PDF Teklif İndir", data=pdf_olustur(s_musteri, s_tc_tel, s_tip, ai_teminat_ozeti, f"{toplam_saglik_primi:,} TL"), file_name=f"Grimset_Saglik_{s_musteri.replace(' ','_')}.pdf", mime="application/pdf", use_container_width=True)

elif sayfa == "🏢 Kurumsal Filo (B2B)":
    st.title("🏢 Kurumsal Filo Yönetimi & B2B Talepleri")
    st.markdown("---")
    if sh:
        st.subheader("🔔 B2B Şirketlerinden Gelen (İK) Talepler")
        try:
            talepler = sh.worksheet("B2B Talepler").get_all_records()
            bekleyenler = [t for t in talepler if t.get("Durum") == "Bekliyor"]
            if not bekleyenler: st.success("Şu an İK departmanlarından gelen bekleyen bir talep yok.")
            else:
                for idx, t in enumerate(reversed(bekleyenler)):
                    gercek_idx = len(talepler) - idx
                    with st.expander(f"🚨 {t.get('Firma')} - {t.get('Personel Adı')} ({t.get('Talep Tipi')})"):
                        st.write(f"**TC/Plaka:** {t.get('TC/Plaka')} | **Tarih:** {t.get('Tarih')}")
                        if st.button("✅ Poliçeyi Kestim (Onayla)", key=f"onay_{gercek_idx}"):
                            sh.worksheet("B2B Talepler").update_cell(gercek_idx + 1, 6, "Onaylandı")
                            st.success("Talep onaylandı ve İK paneline yansıdı!")
                            st.rerun()
        except: st.warning("B2B Talepleri tablosu henüz oluşmamış veya boş.")
    
    st.markdown("---")
    st.subheader("🏢 Yeni Filo Teklifi Oluştur")
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
                                try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "B2B Filo Satışı", f"Firma: {f_firma}, Araç Sayısı: {arac_sayisi}")
                                except: pass
                                st.success("B2B Filo teklifi kaydedildi!")
                            except Exception as e: st.error(f"Kayıt Hatası: {e}")
                with col_btn2:
                    st.download_button("📄 PDF İndir", data=filo_pdf_olustur(f_firma, plakalar, f_tip, toplam_filo_primi), file_name=f"Grimset_{f_firma}.pdf", mime="application/pdf", use_container_width=True)

elif sayfa == "⏰ Vade & Otonom Yenileme":
    st.title("⏰ Akıllı Vade & Otonom Yenileme Panosu")
    st.markdown("---")
    if sh:
        try:
            musteriler = sh.worksheet("Müşteri Portföyü").get_all_records()
            policeler = sh.worksheet("Üretilen Poliçeler").get_all_records()
            df_policeler = pd.DataFrame(policeler)
            
            if musteriler:
                bugun = datetime.now().date()
                yaklasanlar = []
                for m in musteriler:
                    vade_str = str(m.get('Vade Tarihi', ''))
                    if vade_str:
                        try:
                            vade_tarihi = datetime.strptime(vade_str, "%Y-%m-%d").date()
                            kalan_gun = (vade_tarihi - bugun).days
                            if -10 <= kalan_gun <= 15:
                                m['kalan_gun'] = kalan_gun
                                yaklasanlar.append(m)
                        except: pass
                
                if yaklasanlar:
                    yaklasanlar.sort(key=lambda x: x['kalan_gun'])
                    st.subheader("🔔 Otonom Yenileme Fırsatları (15 Gün)")
                    
                    for y in yaklasanlar:
                        k_gun = y['kalan_gun']
                        durum_renk = "🔴 SÜRESİ GEÇTİ" if k_gun < 0 else (f"🟠 BUGÜN BİTİYOR" if k_gun == 0 else f"🟡 {k_gun} Gün Kaldı")
                        isim = y.get('Müşteri Adı', '')
                        plaka = y.get('Plaka', '')
                        tel = y.get('Telefon', '')
                        
                        eski_prim_tutari = 0
                        if not df_policeler.empty and 'Plaka' in df_policeler.columns:
                            musteri_pol = df_policeler[df_policeler['Plaka'].astype(str) == str(plaka)]
                            if not musteri_pol.empty:
                                son_prim_str = str(musteri_pol.iloc[-1].get('Toplam Prim', '0'))
                                eski_prim_tutari = temizle_fiyat(son_prim_str)
                        
                        with st.container(border=True):
                            c_y1, c_y2 = st.columns([2, 1])
                            with c_y1:
                                st.markdown(f"**{isim}** - Plaka: {plaka}")
                                st.caption(f"Durum: **{durum_renk}** | Eski Vade: {y.get('Vade Tarihi', '')}")
                            with c_y2:
                                if eski_prim_tutari > 0:
                                    yeni_otonom_prim = int(eski_prim_tutari * 1.40)
                                    st.markdown(f"<div class='otonom-card'>Yapay Zeka Teklifi:<br><b style='font-size:1.2rem;'>{yeni_otonom_prim:,} TL</b></div>", unsafe_allow_html=True)
                                    wp_otonom = f"Sayın {isim},\n{plaka} plakalı aracınızın sigortası {y.get('Vade Tarihi', '')} tarihinde sona ermektedir.\n\nGrimset Studio ayrıcalığıyla, enflasyon korumalı yeni dönem Otonom Yenileme teklifiniz *{yeni_otonom_prim:,} TL*'dir.\n\nSistemin bu özel teklifini onaylayarak poliçenizi hemen kestirmek için bu mesaja *YENİLE* yazarak cevap verebilirsiniz."
                                    wa_link = f"https://wa.me/90{str(tel).replace(' ', '').replace('+90', '').replace('0', '', 1)}?text={urllib.parse.quote(wp_otonom)}"
                                    st.markdown(f'<a href="{wa_link}" target="_blank" style="text-decoration: none;"><div style="background-color: #25D366; color: white; text-align: center; padding: 5px; border-radius: 5px; font-weight: bold;">🤖 Otonom Teklifi WhatsApp\'tan Gönder</div></a>', unsafe_allow_html=True)
                                else:
                                    st.warning("Eski fiyat verisi bulunamadı.")
                else: st.success("Süresi yaklaşan poliçe yok.")
        except Exception as e: st.warning(f"Hata: {e}")

elif sayfa == "📌 Satış Hunisi (Kanban)":
    st.title("📌 Akıllı Satış Hunisi & AI Lead Scoring")
    st.markdown("Satış fırsatlarını yönetin ve AI tahmine dayalı puanlama (Predictive Scoring) ile hangi müşteriyi önce aramanız gerektiğini görün.")
    st.markdown("---")
    
    if sh:
        try:
            ws_huni = sh.worksheet("Satış Hunisi")
            
            with st.expander("➕ Yeni Satış Fırsatı (Aday) Ekle"):
                with st.form("huni_form"):
                    h_isim = st.text_input("Müşteri Adı")
                    h_tel = st.text_input("Telefon")
                    h_konu = st.text_input("İlgilendiği Ürün (Örn: Lüks Araç Kasko, B2B Sağlık)")
                    
                    gecmis_tutarlar = ["Belirtilmemiş"]
                    try:
                        policeler = sh.worksheet("Üretilen Poliçeler").get_all_records()
                        fiyatlar = set([str(p.get("Toplam Prim", "")) for p in policeler if "TL" in str(p.get("Toplam Prim", ""))])
                        gecmis_tutarlar.extend(sorted(list(fiyatlar), key=temizle_fiyat))
                    except: pass
                    gecmis_tutarlar.append("Diğer (Manuel Gir)")
                    
                    h_tutar_secim = st.selectbox("Tahmini Bütçe / Tutar", gecmis_tutarlar)
                    h_tutar_manuel = st.text_input("Özel Tutar Girin") if h_tutar_secim == "Diğer (Manuel Gir)" else ""
                    
                    if st.form_submit_button("Adayı Huniye Ekle", type="primary"):
                        if h_isim and h_konu:
                            zaman_id = datetime.now().strftime("%Y%m%d%H%M%S")
                            tarih = datetime.now().strftime("%Y-%m-%d")
                            final_tutar = h_tutar_manuel if h_tutar_secim == "Diğer (Manuel Gir)" else ("" if h_tutar_secim == "Belirtilmemiş" else h_tutar_secim)
                            ws_huni.append_row([zaman_id, tarih, h_isim, h_tel, h_konu, final_tutar, "Yeni Aday", st.session_state.kullanici_adi])
                            try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Yeni Aday Eklendi", f"Aday: {h_isim}, Ürün: {h_konu}")
                            except: pass
                            st.success(f"{h_isim} huniye eklendi! AI skorlaması için tabloyu kontrol edin.")
                            st.rerun()
                        else: st.warning("İsim ve Ürün girin.")
            
            st.markdown("### 📊 AI Destekli Aktif Fırsatlar Tablosu")
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
                            if r_tut: st.markdown(f"💰 **Tutar:** {r_tut}")
                            st.caption(f"💼 Sorumlu: {r_sorumlu}")
                            
                            # YENİ: AI LEAD SCORING (TAHMİNE DAYALI PUANLAMA)
                            if r_asama in ["Yeni Aday", "Görüşülüyor"]:
                                ai_skor_btn = st.button("🤖 Kapanma İhtimalini Hesapla", key=f"skor_{r_id}", use_container_width=True)
                                if ai_skor_btn:
                                    with st.spinner("AI analiz ediyor..."):
                                        prompt = f"""Bir sigorta satış uzmanısın. Elimde bir satış fırsatı (Lead) var.
Aday: {r_isim}, İlgilendiği Ürün: {r_konu}, Tahmini Bütçe: {r_tut}, Şu anki Aşama: {r_asama}.
Bu verileri analiz ederek bu satışın başarıyla kapanma (satın alma) ihtimalini 1 ile 100 arasında tahmin et. 
Eğer ürün lüks kasko veya kurumsal B2B gibi yüksek kârlı bir şeyse ve bütçe yüksekse puanı 80 üstü ver. 
SADECE aşağıdaki formatta yanıt ver, başka hiçbir şey yazma:
SKOR: [1-100 arası sayı] - [Kısa 1 cümlelik neden]"""
                                        try:
                                            ai_yanit = client.models.generate_content(model=TEXT_MODEL, contents=prompt).text
                                            skor_metni = ai_yanit.replace("SKOR:", "").strip()
                                            skor_sayi = int(skor_metni.split("-")[0].strip()) if "-" in skor_metni and skor_metni.split("-")[0].strip().isdigit() else 50
                                            
                                            renk = "#2ecc71" if skor_sayi >= 80 else ("#f1c40f" if skor_sayi >= 50 else "#e74c3c")
                                            etiket = "🔥 SICAK SATIŞ (ÖNCE ARA!)" if skor_sayi >= 80 else "⏳ Normal Aday"
                                            
                                            st.markdown(f"""
                                            <div style="background-color: #1e1e1e; border-left: 4px solid {renk}; padding: 10px; margin-top: 5px; border-radius: 5px;">
                                                <b style="color: {renk};">AI Kapanma Skoru: {skor_sayi}/100</b><br>
                                                <span style="font-size: 0.8rem; color: #ccc;">{etiket}</span><br>
                                                <i style="font-size: 0.8rem;">{ai_yanit.split("-")[1].strip() if "-" in ai_yanit else ""}</i>
                                            </div>
                                            """, unsafe_allow_html=True)
                                        except Exception as e: st.error("Skor hesaplanamadı.")
                            
                            secili_index = ["Yeni Aday", "Görüşülüyor", "Teklif Verildi", "Kazanıldı", "İptal Edildi"].index(r_asama) if r_asama in ["Yeni Aday", "Görüşülüyor", "Teklif Verildi", "Kazanıldı", "İptal Edildi"] else 0
                            yeni_asama = st.selectbox("Aşama", ["Yeni Aday", "Görüşülüyor", "Teklif Verildi", "Kazanıldı", "İptal Edildi"], index=secili_index, key=f"asama_{r_id}", label_visibility="collapsed")
                            
                            if yeni_asama != r_asama:
                                ws_huni.update_cell(idx + 2, 7, yeni_asama)
                                try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Kanban Güncellemesi", f"{r_isim}: {r_asama} -> {yeni_asama}")
                                except: pass
                                st.rerun()
            else: st.info("Takip edilen fırsat yok. Sisteme yeni adaylar ekleyin.")
        except Exception as e: st.warning(f"Bağlantı hatası: {e}")

elif sayfa == "🚗 Hasar Asistanı & Süreç Yönetimi":
    st.title("🚗 Kaza ve Hasar Destek & Süreç Yönetimi (AI Suistimal Kontrol)")
    st.markdown("---")
    st.markdown("### ➕ Yeni Hasar Analizi ve Dosya Açılışı")
    h_col1, h_col2 = st.columns([1, 2], gap="large")
    with h_col1:
        h_isim = st.text_input("Müşteri Adı Soyadı")
        h_plaka = st.text_input("Araç Plakası")
        h_beyan = st.text_area("Müşteri Beyanı / Kaza Senaryosu", placeholder="Örn: Kırmızı ışıkta dururken bana arkadan çarptılar...")
        h_gorseller = st.file_uploader("Kaza ve Tutanak Fotoğrafları", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
        
        if h_gorseller:
            gorsel_sutunlari = st.columns(min(len(h_gorseller), 3))
            for idx, img in enumerate(h_gorseller[:3]): gorsel_sutunlari[idx].image(img, use_container_width=True)
            
        if st.button("🔍 Hasarı ve Suistimal Riskini Analiz Et", type="primary", use_container_width=True):
            if h_isim and h_plaka and h_gorseller and h_beyan:
                with st.spinner("Adli bilişim yapay zekası fiziksel hasarı ve müşteri beyanını çapraz sorguluyor..."):
                    st.session_state.son_kaza_analizi = kaza_analizi_yap(h_gorseller, h_plaka, h_isim, h_beyan)
            else: st.warning("İsim, Plaka, Beyan ve Fotoğraf zorunludur.")
            
    with h_col2:
        if "son_kaza_analizi" in st.session_state and st.session_state.son_kaza_analizi:
            st.success("Rapor Başarıyla Oluşturuldu!")
            st.info(st.session_state.son_kaza_analizi)
            if st.button("💾 Hasar Dosyasını Aç (Kaydet)"):
                try:
                    sh.worksheet("Hasar Kayıtları").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), h_isim, h_plaka, st.session_state.son_kaza_analizi, "İnceleniyor"])
                    try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Hasar Dosyası Açıldı", f"Plaka: {h_plaka}")
                    except: pass
                    st.success("Dosya açıldı ve sisteme kaydedildi!")
                except Exception as e: st.error(f"Hata: {e}")

    st.markdown("---")
    st.markdown("### 📂 Aktif Hasar Dosyaları ve Süreç Takibi")
    if sh:
        try:
            ws_hasar = sh.worksheet("Hasar Kayıtları")
            tum_hasarlar = ws_hasar.get_all_values()
            if len(tum_hasarlar) > 1:
                hasar_satirlari = tum_hasarlar[1:]
                for idx, h_row in enumerate(reversed(hasar_satirlari)):
                    gercek_idx = len(hasar_satirlari) - idx
                    if len(h_row) >= 4:
                        r_tar, r_isim, r_plaka, r_rapor = h_row[0], h_row[1], h_row[2], h_row[3]
                        r_durum = h_row[4] if len(h_row) >= 5 else "İnceleniyor"
                        renk = get_status_color(r_durum)
                        with st.expander(f"{r_isim} - Plaka: {r_plaka} | Tarih: {r_tar}"):
                            st.markdown(f"<span class='status-badge' style='background-color: {renk};'>Mevcut Durum: {r_durum}</span>", unsafe_allow_html=True)
                            st.write(f"**Hasar Raporu:**\n{r_rapor}")
                            secenekler = ["İnceleniyor", "Eksper Atandı", "Onarımda", "Ödeme Bekleniyor", "Tamamlandı"]
                            secili_index = secenekler.index(r_durum) if r_durum in secenekler else 0
                            yeni_durum = st.selectbox("Müşteri Portalında Görünecek Durumu Güncelle", secenekler, index=secili_index, key=f"hdurum_{gercek_idx}")
                            if yeni_durum != r_durum:
                                ws_hasar.update_cell(gercek_idx + 1, 5, yeni_durum)
                                try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Hasar Durumu Güncellendi", f"{r_plaka} durumu değiştirildi: {yeni_durum}")
                                except: pass
                                st.success("Durum güncellendi! Müşteri portalına yansıdı.")
                                st.rerun()
            else:
                st.info("Sistemde açık hasar dosyası bulunmuyor.")
        except Exception as e:
            st.warning(f"Hasar dosyaları çekilirken bir hata oluştu: {e}")

elif sayfa == "🗄️ Dijital Evrak Kasası":
    st.title("🗄️ Müşteri Dijital Evrak Kasası (Cloud Vault)")
    st.markdown("---")
    if sh:
        try:
            musteriler = sh.worksheet("Müşteri Portföyü").get_all_records()
            if not musteriler: st.warning("Sistemde kayıtlı müşteri bulunmuyor.")
            else:
                df_musteri = pd.DataFrame(musteriler)
                musteri_secenekleri = df_musteri.apply(lambda x: f"{str(x.get('Plaka', ''))} - {str(x.get('Müşteri Adı', ''))}", axis=1).unique()
                secilen_musteri_bilgi = st.selectbox("Evrak Yüklenecek veya Görüntülenecek Müşteriyi Seçin:", musteri_secenekleri)
                
                if secilen_musteri_bilgi:
                    secilen_plaka = secilen_musteri_bilgi.split(" - ")[0].strip()
                    secilen_isim = secilen_musteri_bilgi.split(" - ")[1].strip()
                    st.markdown("---")
                    c_kasa1, c_kasa2 = st.columns([1, 1.5], gap="large")
                    with c_kasa1:
                        st.subheader("📤 Kasaya Evrak Yükle")
                        with st.form("evrak_yukle_form"):
                            evrak_tipi = st.selectbox("Evrak Tipi", ["Ruhsat", "Kimlik (Önlü Arkalı)", "Ehliyet", "Eski Poliçe", "Araç Fotoğrafı", "Sözleşme / Diğer"])
                            yuklenen_evrak = st.file_uploader("Dosyayı Seçin", type=["jpg", "jpeg", "png", "pdf"])
                            if st.form_submit_button("Güvenli Kasaya Ekle"):
                                if yuklenen_evrak:
                                    zaman_etiketi = datetime.now().strftime("%Y%m%d%H%M%S")
                                    yeni_dosya_adi = f"{secilen_plaka}_{zaman_etiketi}_{yuklenen_evrak.name}"
                                    dosya_kayit_yolu = os.path.join(EVRAK_KASASI_KLASORU, yeni_dosya_adi)
                                    with open(dosya_kayit_yolu, "wb") as f: f.write(yuklenen_evrak.getbuffer())
                                    sh.worksheet("Evrak Kasası").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), secilen_isim, secilen_plaka, evrak_tipi, yeni_dosya_adi, st.session_state.kullanici_adi])
                                    try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Evrak Kasaya Eklendi", f"Tip: {evrak_tipi}, Müşteri: {secilen_plaka}")
                                    except: pass
                                    st.success(f"{evrak_tipi} dosyası kasaya başarıyla kilitlendi!")
                                    st.rerun()
                                else: st.warning("Lütfen yüklenecek bir dosya seçin.")

                    with c_kasa2:
                        st.subheader("📂 Müşterinin Kasasındaki Evraklar")
                        try:
                            tum_evraklar = sh.worksheet("Evrak Kasası").get_all_records()
                            bu_musterinin_evraklari = [e for e in tum_evraklar if str(e.get("Plaka", "")) == secilen_plaka]
                            if not bu_musterinin_evraklari: st.info("Bu müşterinin kasasında henüz bir evrak bulunmuyor.")
                            else:
                                for evrak in reversed(bu_musterinin_evraklari):
                                    with st.container(border=True):
                                        c_liste1, c_liste2 = st.columns([3, 1])
                                        with c_liste1:
                                            st.markdown(f"**📑 {evrak.get('Evrak Tipi', '')}**")
                                            st.caption(f"Tarih: {evrak.get('Tarih', '')} | Ekleyen: {evrak.get('Ekleyen', '')}")
                                        with c_liste2:
                                            dosya_adi = evrak.get('Dosya Adı', '')
                                            dosya_yolu = os.path.join(EVRAK_KASASI_KLASORU, dosya_adi)
                                            if os.path.exists(dosya_yolu):
                                                with open(dosya_yolu, "rb") as file:
                                                    mime_type = "application/pdf" if dosya_adi.lower().endswith(".pdf") else "image/png"
                                                    st.download_button(label="İndir", data=file, file_name=dosya_adi, mime=mime_type, key=f"dl_{dosya_adi}")
                                            else: st.error("Dosya yok.")
                        except Exception as e: st.warning("Hata.")
        except Exception as e: st.warning(f"Bağlantı hatası: {e}")

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
        if st.button("Kıyasla"): 
            st.info("Karşılaştırma motoru aktif! (AI Analizi)")

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

elif sayfa == "📈 LTV & Churn Analizi" and st.session_state.rol == "Admin":
    st.title("📈 Mikroekonomik LTV ve Churn (Ayrılma) Analizi")
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
                    secilen_musteri = st.selectbox("Analiz Edilecek Müşteriyi Seçin:", musteri_listesi)
                    if st.button("🧠 LTV ve Churn Riskini Hesapla", type="primary", use_container_width=True):
                        with st.spinner("Mikroekonomik veriler derleniyor..."):
                            m_data = df_police[df_police['Müşteri Adı'] == secilen_musteri]
                            islem_sayisi = len(m_data)
                            toplam_ciro = m_data['Toplam Prim'].apply(lambda x: int(str(x).replace(' TL', '').replace(',', '')) if str(x).replace(' TL', '').replace(',', '').isdigit() else 0).sum()
                            if 'Net Komisyon' in m_data.columns: ltv_degeri = m_data['Net Komisyon'].apply(temizle_fiyat).sum()
                            else: ltv_degeri = toplam_ciro * 0.10
                            churn_risk = max(10, 95 - (islem_sayisi * 20))
                            risk_class = "churn-high" if churn_risk >= 50 else "churn-low"
                            risk_durum = "YÜKSEK RİSK" if churn_risk >= 50 else "DÜŞÜK RİSK"
                            c_ltv1, c_ltv2, c_ltv3 = st.columns(3)
                            with c_ltv1: st.markdown(f"<div style='text-align:center; padding: 15px; border: 1px solid #333; border-radius: 8px;'><h4>Toplam İşlem</h4><h2>{islem_sayisi} Adet</h2></div>", unsafe_allow_html=True)
                            with c_ltv2: st.markdown(f"<div style='text-align:center; padding: 15px; border: 1px solid #333; border-radius: 8px; background-color: #1a2980;'><h4>💰 LTV (Net Kâr)</h4><h2 style='color:#00ff7f;'>{int(ltv_degeri):,} TL</h2></div>", unsafe_allow_html=True)
                            with c_ltv3: st.markdown(f"<div style='text-align:center; padding: 15px; border: 1px solid #333; border-radius: 8px;'><h4>⚠️ Churn Riski</h4><h2 class='{risk_class}'>%{churn_risk}</h2></div>", unsafe_allow_html=True)
                            st.markdown("---")
                            prompt = f"Sen aktüersin. Müşteri: {secilen_musteri}, Ciro: {toplam_ciro} TL, LTV: {ltv_degeri} TL, İşlem: {islem_sayisi}, Churn Riski: %{churn_risk}. Bu müşteriyi kaybetmemek için satış ekibine tam olarak ne kadarlık bir iskonto/promosyon tanımlamaları gerektiğini ve telefonda nasıl bir taktik izlemeleri gerektiğini söyle."
                            try: st.info(client.models.generate_content(model=TEXT_MODEL, contents=prompt).text)
                            except Exception as e: st.error(f"AI bağlantı hatası: {e}")
        except Exception as e: st.warning(f"Hata: {e}")

elif sayfa == "💸 Gider Yönetimi" and st.session_state.rol == "Admin":
    st.title("💸 Şirket Gider Yönetimi")
    st.markdown("---")
    g_col1, g_col2 = st.columns([1, 1.5], gap="large")
    with g_col1:
        st.subheader("➕ Yeni Gider Ekle")
        with st.form("gider_form"):
            g_kalem = st.text_input("Gider Adı/Açıklaması")
            g_kategori = st.selectbox("Kategori", ["Kira & Aidat", "Personel Maaş/Prim", "Pazarlama & Reklam", "Ofis İçi Harcama", "Faturalar", "Diğer"])
            g_tutar = st.number_input("Tutar (TL)", min_value=0)
            if st.form_submit_button("Gideri Kaydet"):
                if g_kalem and g_tutar > 0 and sh:
                    try:
                        zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        sh.worksheet("Şirket Giderleri").append_row([zaman, g_kalem, g_kategori, f"{g_tutar} TL", st.session_state.kullanici_adi])
                        try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Yeni Gider Eklendi", f"Kalem: {g_kalem}, Tutar: {g_tutar}")
                        except: pass
                        st.success("Gider başarıyla işlendi!")
                        st.rerun()
                    except Exception as e: st.error(f"Kayıt Hatası: {e}")
                else: st.warning("Açıklama ve tutar girin.")
    with g_col2:
        st.subheader("📋 Mevcut Şirket Giderleri")
        if sh:
            try:
                giderler = sh.worksheet("Şirket Giderleri").get_all_records()
                if not giderler: st.info("Kaydedilmiş gider bulunmuyor.")
                else: st.dataframe(pd.DataFrame(giderler).iloc[::-1], use_container_width=True)
            except Exception as e: st.warning("Giderler yüklenemedi.")

elif sayfa == "📊 Finansal & Coğrafi Dashboard" and st.session_state.rol == "Admin":
    st.title("📊 Yönetici Finansal & Coğrafi Dashboard")
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
            
            toplam_gider = 0
            try:
                giderler = sh.worksheet("Şirket Giderleri").get_all_records()
                if giderler:
                    df_gider = pd.DataFrame(giderler)
                    toplam_gider = df_gider['Tutar'].astype(str).str.replace(' TL', '').str.replace(',', '').astype(float).sum()
            except: pass
            
            saf_kar = toplam_komisyon - toplam_gider
            renk = "#00FF7F" if saf_kar >= 0 else "#FF4500"
            durum_metni = "Bu tutar tüm masraflar çıktıktan sonra şirketinizin kasasında kalan net nakit kârdır." if saf_kar >= 0 else "Dikkat! Giderleriniz komisyon gelirlerinizi aşmış durumda."
            
            st.markdown(f"""
            <div style="background: linear-gradient(90deg, #1A2980 0%, #26D0CE 100%); padding: 20px; border-radius: 10px; color: white; text-align: center; margin-bottom: 20px; box-shadow: 0px 4px 15px rgba(0,0,0,0.3);">
                <h2 style="margin:0; color: white;">💰 GRIMSET STUDIO GERÇEK SAF KÂR</h2>
                <h1 style="margin:0; font-size: 3.5rem; color: {renk};">{int(saf_kar):,} TL</h1>
                <p style="margin:0; opacity: 0.9;">{durum_metni}</p>
                <div style="margin-top: 10px; font-size: 1.1rem;">
                    <span style="color: #A9DFBF;">Brüt Komisyon: +{int(toplam_komisyon):,} TL</span> | 
                    <span style="color: #F5B041;">Toplam Gider: -{int(toplam_gider):,} TL</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("---")
            st.subheader("🗺️ Türkiye Coğrafi Risk ve Satış Haritası")
            def get_plaka_kodu(plaka_str):
                match = re.search(r'^\d{2}', str(plaka_str))
                if match: return match.group(0)
                return "Bilinmiyor"

            df['İl Kodu'] = df['Plaka'].apply(get_plaka_kodu)
            il_koordinatlari = {
                "16": ("Bursa / Gemlik", 40.4286, 29.1578), "34": ("İstanbul", 41.0082, 28.9784),
                "06": ("Ankara", 39.9208, 32.8541), "35": ("İzmir", 38.4192, 27.1287),
                "07": ("Antalya", 36.8969, 30.7133), "01": ("Adana", 37.0000, 35.3213),
            }
            df_geo = df[df['İl Kodu'].isin(il_koordinatlari.keys())].copy()
            if not df_geo.empty:
                df_geo_grouped = df_geo.groupby('İl Kodu')['Saf Prim'].sum().reset_index()
                df_geo_grouped['Şehir'] = df_geo_grouped['İl Kodu'].apply(lambda x: il_koordinatlari[x][0])
                df_geo_grouped['Lat'] = df_geo_grouped['İl Kodu'].apply(lambda x: il_koordinatlari[x][1])
                df_geo_grouped['Lon'] = df_geo_grouped['İl Kodu'].apply(lambda x: il_koordinatlari[x][2])
                fig_map = px.scatter_mapbox(df_geo_grouped, lat="Lat", lon="Lon", size="Saf Prim", color="Şehir", hover_name="Şehir", size_max=50, zoom=5, mapbox_style="carto-darkmatter")
                fig_map.update_layout(margin={"r":0,"t":40,"l":0,"b":0})
                st.plotly_chart(fig_map, use_container_width=True)
            
            st.markdown("---")
            st.subheader("🧠 AI Satış & Performans Koçu (Kanban Analizi)")
            if st.button("Satış Ekibini ve Bekleyen Fırsatları Analiz Et", type="secondary"):
                with st.spinner("Gemini Kanban panosunu inceliyor... Lütfen bekleyin."):
                    try:
                        huni_verileri = sh.worksheet("Satış Hunisi").get_all_records()
                        aktif_firsatlar = [f for f in huni_verileri if f.get('Aşama') not in ['Kazanıldı', 'İptal Edildi']]
                        if not aktif_firsatlar: st.success("Şu an bekleyen aktif bir satış fırsatı yok. Ekip harika çalışıyor!")
                        else:
                            firsat_ozeti = ""
                            toplam_bekleyen_tutar = 0
                            for f in aktif_firsatlar:
                                tutar_str = str(f.get('Tahmini Tutar', '0')).replace(' TL', '').replace(',', '').replace('.', '')
                                try: tutar = float(tutar_str) if tutar_str else 0
                                except: tutar = 0
                                toplam_bekleyen_tutar += tutar
                                firsat_ozeti += f"- Müşteri: {f.get('Müşteri Adı')}, Aşama: {f.get('Aşama')}, Tutar: {tutar} TL, Sorumlu: {f.get('Sorumlu')}\n"
                            prompt = f"Sen Grimset Studio Satış Müdürüsün. Kanban'da bekleyen potansiyel ciro: {toplam_bekleyen_tutar} TL. Personel performansını analiz et ve aksiyon planı çıkar.\n{firsat_ozeti}"
                            st.info(client.models.generate_content(model=TEXT_MODEL, contents=prompt).text)
                    except Exception as e: st.error(f"Hata: {e}")
            
            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            col1.metric("💼 Toplam Kesilen Poliçe", f"{len(df)} Adet")
            col2.metric("📈 Toplam Üretim (Ciro)", f"{int(toplam_ciro):,} TL")
            col3.metric("🏆 En Çok Satılan", str(df['Poliçe Tipi'].mode()[0]))
            
            st.markdown("---")
            st.subheader("🏆 Satış Ekibi Kâr Getirisi")
            satis_performansi = df.groupby('Satış Temsilcisi')['Net Komisyon'].sum().reset_index().sort_values(by='Net Komisyon', ascending=False)
            st.plotly_chart(px.bar(satis_performansi, x='Satış Temsilcisi', y='Net Komisyon', text_auto='.2s', color='Satış Temsilcisi'), use_container_width=True)
            
            st.markdown("---")
            g_col1, g_col2 = st.columns(2)
            with g_col1: st.plotly_chart(px.pie(df, names='Poliçe Tipi', values='Net Komisyon', hole=0.4, color_discrete_sequence=px.colors.sequential.Teal, title="Ürün Bazlı Kâr Dağılımı"), use_container_width=True)
            with g_col2:
                df['Kısa Tarih'] = pd.to_datetime(df['Tarih']).dt.date
                st.plotly_chart(px.bar(df.groupby('Kısa Tarih')['Net Komisyon'].sum().reset_index(), x='Kısa Tarih', y='Net Komisyon', text_auto='.2s', color_discrete_sequence=['#4CAF50'], title="Günlük Komisyon Akışı"), use_container_width=True)
            
            st.markdown("---")
            st.subheader("Son Kesilen Poliçeler")
            st.dataframe(df[['Tarih', 'Satış Temsilcisi', 'Müşteri Adı', 'Poliçe Tipi', 'Toplam Prim', 'Net Komisyon']].tail(10).iloc[::-1], use_container_width=True)
        except Exception as e: st.warning(f"Hata: {e}")

elif sayfa == "🔐 Denetim İzi (Audit Log)" and st.session_state.rol == "Admin":
    st.title("🔐 Kurumsal Denetim İzi ve Anti-Sabotaj Sistemi")
    st.markdown("Şirket personelinin ve müşterilerin sistem içindeki tüm hareketlerini, saniyesi saniyesine buradan takip edebilirsiniz.")
    st.markdown("---")
    if sh:
        try:
            loglar = sh.worksheet("Audit Log").get_all_records()
            if not loglar:
                st.info("Henüz sistemde kaydedilmiş bir hareket bulunmuyor.")
            else:
                df_log = pd.DataFrame(loglar)
                st.dataframe(df_log.iloc[::-1], use_container_width=True, height=600)
        except Exception as e:
            st.warning(f"Loglar yüklenirken bir hata oluştu: {e}")

    # YENİ MODÜL: MÜŞTERİ TARAFI TICKET SİSTEMİ
elif sayfa == "🎫 Destek Talebi (Ticket)" and st.session_state.rol == "Musteri":
    st.title("🎫 7/24 AI Destek ve Ticket Merkezi")
    st.markdown("Sorularınızı iletin. Yapay Zeka asistanımız saniyeler içinde çözsün, gerekirse müşteri temsilcinize aktarsın.")
    st.markdown("---")
    if sh:
        try: ws_ticket = sh.worksheet("Destek Talepleri")
        except:
            ws_ticket = sh.add_worksheet(title="Destek Talepleri", rows="1000", cols="20")
            ws_ticket.append_row(["Tarih", "Müşteri Adı", "Plaka", "Soru", "Cevap", "Durum", "Sorumlu"])
            
        with st.form("ticket_form"):
            soru = st.text_area("Nasıl yardımcı olabiliriz?", placeholder="Örn: Poliçemde cam kırılması muafiyetli mi? Veya poliçe iptali yapmak istiyorum...")
            if st.form_submit_button("Talebi Gönder", type="primary"):
                if soru:
                    with st.spinner("Yapay Zeka asistanımız talebinizi inceliyor..."):
                        prompt = f"""Sen Grimset Studio'nun Müşteri Destek Yapay Zekasısın.
Müşteri Sorusu: "{soru}"
Görevlerin:
1. Soru sigorta teminatları, genel süreçler, hasar adımları veya basit bir bilgi alma işlemiyse resmi, güven veren ve ÇÖZÜCÜ bir dille yanıtla.
2. Soru fiyata itiraz, özel poliçe iptali, iade, karmaşık bir talep veya insan onayı (müşteri temsilcisi) gerektiren bir durumsa ŞU ETİKETİ İÇEREN BİR YANIT VER: "[HUMAN]". Müşteriye şunu söyle: "Talebinizin detaylarını inceledim. Bu konu özel işlem gerektirdiği için dosyanızı hemen müşteri temsilcimize aktarıyorum. Size en kısa sürede dönüş yapacağız." """
                        try:
                            ai_yanit = client.models.generate_content(model=TEXT_MODEL, contents=prompt).text
                            durum = "Açık (İnsan Bekliyor)" if "[HUMAN]" in ai_yanit else "Çözüldü (AI)"
                            temiz_yanit = ai_yanit.replace("[HUMAN]", "").strip()
                            
                            ws_ticket.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state.kullanici_adi, st.session_state.musteri_plaka, soru, temiz_yanit, durum, "AI Asistan"])
                            st.success("Talebiniz işleme alındı!")
                            st.info(f"**Grimset Asistan:**\n\n{temiz_yanit}")
                        except Exception as e: st.error("Sistem yoğun.")
                else: st.warning("Lütfen bir soru girin.")
                
        st.markdown("---")
        st.subheader("📋 Geçmiş Destek Talepleriniz")
        try:
            talepler = ws_ticket.get_all_records()
            benim_taleplerim = [t for t in talepler if str(t.get("Plaka", "")) == st.session_state.musteri_plaka]
            if not benim_taleplerim: st.caption("Geçmiş talebiniz bulunmuyor.")
            else:
                for t in reversed(benim_taleplerim):
                    renk = "#e74c3c" if "Açık" in t.get("Durum", "") else "#2ecc71"
                    with st.expander(f"Soru: {t.get('Soru', '')[:40]}..."):
                        st.markdown(f"<span class='status-badge' style='background-color:{renk}'>{t.get('Durum', '')}</span> - Tarih: {t.get('Tarih', '')}", unsafe_allow_html=True)
                        st.write(f"**Sorunuz:** {t.get('Soru', '')}")
                        st.write(f"**Yanıt ({t.get('Sorumlu', '')}):** {t.get('Cevap', '')}")
        except: pass

# YENİ MODÜL: PERSONEL/ADMİN TARAFI TICKET MASASI
elif sayfa == "🎫 Müşteri Destek Masası" and st.session_state.rol in ["Admin", "Satis"]:
    st.title("🎫 Müşteri Destek ve Ticket Masası")
    st.markdown("Yapay zekanın çözemediği ve uzman temsilciye aktardığı (Açık) destek taleplerini buradan yönetin.")
    st.markdown("---")
    if sh:
        try:
            ws_ticket = sh.worksheet("Destek Talepleri")
            talepler = ws_ticket.get_all_records()
            acik_talepler = [t for t in talepler if "Açık" in t.get("Durum", "")]
            
            if not acik_talepler:
                st.success("🎉 Harika! Tüm müşteri talepleri Yapay Zeka tarafından veya ekibinizce çözülmüş. Bekleyen işlem yok.")
            else:
                st.warning(f"Dikkat: Bekleyen {len(acik_talepler)} adet destek talebi var!")
                for idx, t in enumerate(reversed(acik_talepler)):
                    # Excel satır indexini doğru bulmak için
                    gercek_idx = len(talepler) - idx
                    with st.container(border=True):
                        st.markdown(f"**Müşteri:** {t.get('Müşteri Adı')} (Plaka: {t.get('Plaka')}) | **Tarih:** {t.get('Tarih')}")
                        st.info(f"**Soru / Talep:**\n{t.get('Soru')}")
                        st.caption(f"Yapay Zekanın Verdiği İlk Yanıt: {t.get('Cevap')}")
                        
                        yeni_cevap = st.text_area("Müşteriye Yanıtınız:", key=f"cevap_{gercek_idx}")
                        if st.button("Müşteriye Yanıtla ve Talebi Kapat", key=f"btn_{gercek_idx}", type="primary"):
                            if yeni_cevap:
                                ws_ticket.update_cell(gercek_idx + 1, 5, yeni_cevap) # Cevap kolonu
                                ws_ticket.update_cell(gercek_idx + 1, 6, "Çözüldü (İnsan)") # Durum
                                ws_ticket.update_cell(gercek_idx + 1, 7, st.session_state.kullanici_adi) # Sorumlu
                                try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Ticket Çözüldü", f"Müşteri: {t.get('Müşteri Adı')}")
                                except: pass
                                st.success("Talep başarıyla yanıtlandı ve kapatıldı!")
                                st.rerun()
                            else: st.warning("Lütfen bir yanıt yazın.")
        except Exception as e: st.warning("Destek tablosu henüz oluşturulmamış veya okunurken hata oluştu.")

        # YENİ MODÜL: 🌐 GRIMSET DEVELOPER API
elif sayfa == "🌐 Developer API & Entegrasyon" and st.session_state.rol == "Admin":
    st.title("🌐 Grimset Developer API & Entegrasyon Portalı")
    st.markdown("Dış platformlardan (Web siteniz, mobil uygulamanız veya bayi sistemleriniz) Grimset CRM'e otomatik veri akışı sağlamak için gizli API anahtarları oluşturun ve yönetin.")
    st.markdown("---")
    
    import uuid
    
    if sh:
        # Sheet kontrolü/oluşturma
        try: ws_api = sh.worksheet("API_Keys")
        except:
            ws_api = sh.add_worksheet(title="API_Keys", rows="100", cols="10")
            ws_api.append_row(["Tarih", "Uygulama Adı", "API Anahtarı", "Durum", "Oluşturan"])
        
        c_api1, c_api2 = st.columns([1, 1.5], gap="large")
        with c_api1:
            st.subheader("🔑 Yeni API Anahtarı Üret")
            with st.form("api_form"):
                app_name = st.text_input("Bağlanacak Uygulama / Platform Adı", placeholder="Örn: Grimset Web Sitesi İletişim Formu")
                if st.form_submit_button("API Anahtarı Oluştur", type="primary"):
                    if app_name:
                        # Gerçekçi ve güvenli bir anahtar formatı
                        yeni_key = f"gr_live_{uuid.uuid4().hex}"
                        ws_api.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), app_name, yeni_key, "Aktif", st.session_state.kullanici_adi])
                        try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "API Anahtarı Üretildi", f"Uygulama: {app_name}")
                        except: pass
                        st.success(f"Anahtar Başarıyla Üretildi!")
                        st.code(yeni_key, language="text")
                        st.rerun()
                    else: st.warning("Lütfen uygulama adını girin.")
        
        with c_api2:
            st.subheader("🔌 Aktif Entegrasyonlar")
            try:
                api_kayitlari = ws_api.get_all_records()
                if not api_kayitlari: st.info("Sistemde henüz aktif bir API entegrasyonu bulunmuyor.")
                else: 
                    # Anahtarın bir kısmını gizleyerek gösterelim (Güvenlik)
                    df_api = pd.DataFrame(api_kayitlari)
                    df_api['API Anahtarı'] = df_api['API Anahtarı'].apply(lambda x: f"{str(x)[:12]}...{str(x)[-4:]}")
                    st.dataframe(df_api.iloc[::-1], use_container_width=True)
            except Exception as e: st.warning(f"Tablo okunamadı: {e}")
        
        st.markdown("---")
        st.subheader("📖 API Dokümantasyonu (Örnek Kullanım)")
        st.markdown("Aşağıdaki Python örneğini kullanarak dış sistemlerinizden **Satış Hunisine (Kanban)** otomatik Aday (Lead) gönderebilirsiniz:")
        
        st.code("""
# Python (Requests) ile Grimset CRM'e Dışarıdan Müşteri Gönderme Örneği
import requests

url = "https://api.grimset.studio/v1/leads" # Temsili Uç Nokta
headers = {
    "Authorization": "Bearer gr_live_senin_gizli_anahtarin_buraya_gelecek",
    "Content-Type": "application/json"
}
payload = {
    "isim": "Dışarıdan Gelen Yeni Aday",
    "telefon": "0555 123 45 67",
    "ilgili_urun": "Filo Kasko",
    "kaynak": "Grimset Web Sitesi"
}

response = requests.post(url, json=payload, headers=headers)

if response.status_code == 201:
    print("Müşteri başarıyla Grimset Satış Hunisine (Kanban) eklendi!")
        """, language="python")

        # YENİ MODÜL: 📅 AI DESTEKLİ AJANDA VE RANDEVU SİSTEMİ
elif sayfa == "📅 Ajanda & Randevu" and st.session_state.rol in ["Admin", "Satis"]:
    st.title("📅 AI Destekli Ajanda ve Toplantı Merkezi")
    st.markdown("Kurumsal (B2B) veya VIP müşterilerle yapacağınız toplantıları planlayın, Yapay Zeka sizin için 'Kapanış (Closing)' taktikleri hazırlasın.")
    st.markdown("---")
    
    if sh:
        # Sheet kontrolü/oluşturma
        try: ws_randevu = sh.worksheet("Randevular")
        except:
            ws_randevu = sh.add_worksheet(title="Randevular", rows="100", cols="10")
            ws_randevu.append_row(["Tarih", "Saat", "Müşteri Adı", "Konu", "Durum", "Sorumlu"])
            
        c_aj1, c_aj2 = st.columns([1, 1.5], gap="large")
        
        with c_aj1:
            st.subheader("➕ Yeni Toplantı Ayarla")
            with st.form("randevu_form"):
                r_musteri = st.text_input("Müşteri / Firma Adı")
                r_konu = st.text_input("Toplantı Konusu", placeholder="Örn: 50 Araçlık Filo Kasko Görüşmesi")
                
                c_dt1, c_dt2 = st.columns(2)
                r_tarih = c_dt1.date_input("Toplantı Tarihi")
                r_saat = c_dt2.time_input("Toplantı Saati")
                
                if st.form_submit_button("Randevuyu Takvime İşle", type="primary"):
                    if r_musteri and r_konu:
                        ws_randevu.append_row([str(r_tarih), str(r_saat), r_musteri, r_konu, "Bekliyor", st.session_state.kullanici_adi])
                        try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Yeni Randevu", f"{r_musteri} - {r_tarih} {r_saat}")
                        except: pass
                        st.success("Randevu başarıyla takvime işlendi!")
                        st.rerun()
                    else: st.warning("Lütfen müşteri adı ve konuyu giriniz.")
                    
        with c_aj2:
            st.subheader("🗓️ Yaklaşan Toplantılar")
            try:
                randevular = ws_randevu.get_all_records()
                aktif_randevular = [r for r in randevular if str(r.get("Durum", "")) == "Bekliyor"]
                
                if not aktif_randevular:
                    st.info("Yaklaşan bir toplantınız bulunmuyor. Sahaya inme vakti!")
                else:
                    # Tarihe göre sırala (En yakın tarih en üstte)
                    aktif_randevular.sort(key=lambda x: str(x.get('Tarih', '9999-12-31')))
                    
                    for idx, r in enumerate(aktif_randevular):
                        gercek_idx = randevular.index(r) + 2 # Excel satır numarası (1 başlık, 0 tabanlı index)
                        
                        with st.container(border=True):
                            c_r1, c_r2 = st.columns([2, 1])
                            with c_r1:
                                st.markdown(f"**🤝 Müşteri/Firma:** {r.get('Müşteri Adı')}")
                                st.caption(f"🗓️ **{r.get('Tarih')}** | ⏰ **{r.get('Saat')}**")
                                st.write(f"🎯 **Gündem:** {r.get('Konu')}")
                            with c_r2:
                                # Butonları değişkene atadık
                                ai_buton = st.button("🤖 AI Hazırlığı", key=f"ai_prep_{gercek_idx}", use_container_width=True)
                                tamamla_buton = st.button("✅ Yapıldı İşaretle", key=f"tamamla_{gercek_idx}", use_container_width=True)
                                
                            # YENİ EKLENEN YAPI: Butonların basılma olayını dar kolonun DIŞINA, ama kutunun İÇİNE aldık.
                            if tamamla_buton:
                                ws_randevu.update_cell(gercek_idx, 5, "Tamamlandı")
                                try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Toplantı Tamamlandı", f"{r.get('Müşteri Adı')}")
                                except: pass
                                st.success("Toplantı tamamlandı olarak işaretlendi!")
                                st.rerun()
                                
                            if ai_buton:
                                with st.spinner("Gemini strateji üretiyor..."):
                                    prompt = f"""Sen elit bir sigorta ve satış koçusun. Birazdan '{r.get('Müşteri Adı')}' adlı müşteriyle '{r.get('Konu')}' konusunda bir toplantım var. 
Lütfen bu satışı kapatmak, müşterinin olası fiyat itirazlarını önceden savuşturmak ve masadan zaferle ayrılmamı sağlamak için bana 3 maddelik çok sert, vurucu ve net bir taktik ver. Satıcı motivasyonuyla konuş."""
                                    try:
                                        ai_taktik = client.models.generate_content(model=TEXT_MODEL, contents=prompt).text
                                        # Artık bu metin dar kolonda değil, tüm kutu genişliğinde Gündem'in altına dökülecek!
                                        st.info(ai_taktik)
                                    except Exception as e: st.error("AI bağlantı hatası.")
            except Exception as e: st.warning(f"Randevular okunamadı: {e}")

            # YENİ MODÜL: 📡 TELEMATİK VE IOT (SÜRÜŞ ANALİZİ)
elif sayfa == "📡 Telematik (Sürüş Analizi)" and st.session_state.rol in ["Admin", "Satis"]:
    st.title("📡 IoT Telematik & Sürüş Skoru (Pay-How-You-Drive)")
    st.markdown("Müşterilerin araçlarındaki telemetri cihazlarından anlık sürüş verilerini çekin ve Kasko fiyatlarını risk analiziyle kişiselleştirin.")
    st.markdown("---")

    if sh:
        try:
            musteriler = sh.worksheet("Müşteri Portföyü").get_all_records()
            if not musteriler:
                st.warning("Sistemde müşteri bulunmuyor.")
            else:
                df_musteri = pd.DataFrame(musteriler)
                # Sadece plakası olanları (araç sahiplerini) listele
                df_musteri = df_musteri[df_musteri['Plaka'].astype(str).str.strip() != ""]
                musteri_listesi = df_musteri.apply(lambda x: f"{x['Plaka']} - {x['Müşteri Adı']}", axis=1).unique()

                if len(musteri_listesi) == 0:
                    st.info("Kayıtlı plakaya sahip müşteri bulunamadı.")
                else:
                    c_tel1, c_tel2 = st.columns([1, 1.5], gap="large")

                    with c_tel1:
                        st.subheader("🚙 Araç Veri Simülasyonu")
                        secilen_arac = st.selectbox("Sürüş Verisi Çekilecek Araç:", musteri_listesi)

                        st.markdown("*(Aşağıdaki veriler normalde araçtaki çipten veya mobil uygulamadan otomatik çekilir. Test için manuel simüle ediniz)*")
                        hiz_ihlali = st.slider("Aylık Aşırı Hız İhlali (Adet)", 0, 50, 5)
                        ani_fren = st.slider("Ani Fren / Sert İvmelenme (Adet)", 0, 100, 15)
                        gece_surus = st.slider("Gece Sürüş Oranı (00:00 - 06:00) %", 0, 100, 10)
                        aylik_km = st.slider("Aylık Ortalama Mesafe (KM)", 100, 10000, 1200)

                    with c_tel2:
                        st.subheader("📊 Telematik Risk Skoru & Fiyatlama")

                        # Basit Aktüeryal Sürüş Skoru Algoritması (100 üzerinden başlar, hatalarla düşer)
                        base_score = 100
                        ceza_hiz = hiz_ihlali * 1.5
                        ceza_fren = ani_fren * 0.5
                        ceza_gece = (gece_surus - 20) * 0.5 if gece_surus > 20 else 0
                        ceza_km = (aylik_km - 2000) * 0.002 if aylik_km > 2000 else 0

                        toplam_ceza = ceza_hiz + ceza_fren + ceza_gece + ceza_km
                        surus_skoru = max(0, min(100, int(base_score - toplam_ceza)))

                        # Renk ve Finansal Etki Belirleme
                        if surus_skoru >= 80:
                            renk = "#2ecc71" # Yeşil
                            durum = "🌟 Mükemmel Sürücü"
                            fiyat_etkisi = "-%15 İndirim (Ödül)"
                        elif surus_skoru >= 60:
                            renk = "#f1c40f" # Sarı
                            durum = "⚠️ Standart Sürücü"
                            fiyat_etkisi = "Standart Tarife (Etki Yok)"
                        else:
                            renk = "#e74c3c" # Kırmızı
                            durum = "🚨 Yüksek Riskli Sürücü"
                            fiyat_etkisi = "+%25 Sürprim (Ceza)"

                        st.markdown(f"""
                        <div style="background-color: #1e1e1e; padding: 20px; border-radius: 10px; border-left: 5px solid {renk}; box-shadow: 0px 4px 10px rgba(0,0,0,0.3);">
                            <h2 style="margin:0; color: white;">Skor: <span style="color:{renk};">{surus_skoru} / 100</span></h2>
                            <p style="margin-top:5px; font-size: 1.1rem; color: #ccc;">Sürücü Profili: <b>{durum}</b></p>
                            <h4 style="margin-top:10px; color: {renk};">Sonraki Kasko Fiyat Etkisi: {fiyat_etkisi}</h4>
                        </div>
                        """, unsafe_allow_html=True)

                        st.markdown("---")
                        if st.button("🤖 AI Sürücü Geri Bildirim Raporu Oluştur", type="primary", use_container_width=True):
                            with st.spinner("Gemini telemetri verilerini analiz ediyor..."):
                                prompt = f"""Sen Grimset Studio'nun telematik risk aktüerisin. Birazdan '{secilen_arac}' plakalı müşterimize Whatsapp'tan bir aylık sürüş karnesi göndereceksin.
Müşterinin 1 aylık sürüş verisi şu şekilde:
- Aşırı Hız İhlali: {hiz_ihlali} kez
- Ani Fren: {ani_fren} kez
- Gece Sürüş Oranı: %{gece_surus}
Hesaplanan Sürüş Skoru: {surus_skoru}/100 ({durum}). Kaskosuna yansıyacak potansiyel etki: {fiyat_etkisi}.

Lütfen bu verileri yorumlayarak müşteriye doğrudan hitap eden, eğer iyi sürüyorsa tebrik eden ve indirim müjdesi veren; eğer kötü sürüyorsa kibarca uyaran ve poliçe fiyatının artacağını belirten 3-4 cümlelik kısa bir WhatsApp mesajı hazırla."""
                                try:
                                    ai_rapor = client.models.generate_content(model=TEXT_MODEL, contents=prompt).text
                                    st.info(ai_rapor)

                                    wa_link = f"https://wa.me/?text={urllib.parse.quote(ai_rapor)}"
                                    st.markdown(f'<a href="{wa_link}" target="_blank" style="text-decoration: none;"><div style="background-color: #25D366; color: white; text-align: center; padding: 10px; border-radius: 8px; font-weight: bold; margin-bottom: 10px;">💬 Sürücüye WhatsApp\'tan Karnesini Gönder</div></a>', unsafe_allow_html=True)

                                    try: log_action(st.session_state.kullanici_adi, st.session_state.rol, "Telematik Raporu Üretildi", f"Araç: {secilen_arac}, Skor: {surus_skoru}")
                                    except: pass
                                except Exception as e:
                                    st.error("AI bağlantı hatası.")
        except Exception as e: st.warning(f"Bağlantı hatası: {e}")
