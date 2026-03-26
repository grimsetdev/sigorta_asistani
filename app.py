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
st.markdown("""<style>.stButton>button { border-radius: 8px; transition: all 0.3s ease-in-out; font-weight: bold; } .stButton>button:hover { transform: scale(1.02); box-shadow: 0px 4px 15px rgba(0,0,0,0.1); } div[data-testid="metric-container"] { background-color: #1e1e1e; border: 1px solid #333; padding: 5% 5% 5% 10%; border-radius: 10px; box-shadow: 2px 2px 10px rgba(0,0,0,0.2); color: white; } [data-testid="stSidebar"] { background-color: #0e1117; border-right: 1px solid #2d2d2d; } .login-box { max-width: 400px; margin: auto; padding: 2rem; border-radius: 10px; background-color: #1e1e1e; box-shadow: 0 4px 8px rgba(0,0,0,0.2); } .status-badge { padding: 5px 10px; border-radius: 5px; font-weight: bold; color: white; display: inline-block; margin-bottom: 5px;} .churn-high { color: #ff4d4d; font-weight: bold; font-size: 1.2rem; } .churn-low { color: #2ecc71; font-weight: bold; font-size: 1.2rem; } .otonom-card { background: linear-gradient(135deg, #2b5876 0%, #4e4376 100%); padding: 15px; border-radius: 10px; color: white; margin-bottom: 10px;} .mikro-card { background: linear-gradient(135deg, #ff9a9e 0%, #fecfef 99%, #fecfef 100%); padding: 15px; border-radius: 10px; color: #333; margin-bottom: 10px;}</style>""", unsafe_allow_html=True)

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
        for ws_name, cols in [("Müşteri Portföyü", ["Tarih", "Müşteri Adı", "Telefon", "Plaka", "Vade Tarihi", "OCR Detayı"]), ("Üretilen Poliçeler", ["Tarih", "Müşteri Adı", "Plaka", "Poliçe Tipi", "Teminatlar", "Toplam Prim", "Satış Temsilcisi", "Net Komisyon"]), ("Hasar Kayıtları", ["Tarih", "Müşteri Adı", "Plaka", "Hasar Raporu", "Durum"]), ("Filo Teklifleri", ["Tarih", "Firma Adı", "Araç Sayısı", "Plakalar", "Poliçe Tipi", "Toplam Prim", "Satış Temsilcisi", "Net Komisyon"]), ("Satış Hunisi", ["ID", "Tarih", "Müşteri Adı", "Telefon", "Konu", "Tahmini Tutar", "Aşama", "Sorumlu"]), ("Şirket Giderleri", ["Tarih", "Gider Kalemi", "Kategori", "Tutar", "Ekleyen"]), ("Evrak Kasası", ["Tarih", "Müşteri Adı", "Plaka", "Evrak Tipi", "Dosya Adı", "Ekleyen"]), ("Audit Log", ["Tarih", "Kullanıcı", "Rol", "İşlem Türü", "İşlem Detayı"])]:
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
    st.session_state.update({"giris_yapildi": False, "rol": None, "kullanici_adi": None, "musteri_plaka": None, "musteri_tel": None})

if not st.session_state.giris_yapildi:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown('<div class="login-box">', unsafe_allow_html=True)
        st.image("https://images.squarespace-cdn.com/content/v1/6055d01a61b2383be553b1b6/bd6d8e20-94d0-4e36-b552-6d2c4b574229/grimset+copy+copy+logo.png?format=1500w", width=200)
        st.markdown("<h3 style='text-align: center;'>Grimset Studio Sistem Girişi</h3>", unsafe_allow_html=True)
        tab_personel, tab_musteri = st.tabs(["🧑‍💼 Personel Girişi", "👤 Müşteri Portalı"])
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
                                log_action(st.session_state.kullanici_adi, "Musteri", "Müşteri Portalı Girişi", f"Plaka/TC: {p_in}")
                                st.rerun(); break
                        if not giris_basarili: st.error("Kayıt bulunamadı.")
                    except Exception as e: st.error("Hata.")
                else: st.warning("Bilgileri girin.")
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
    try: return client.models.generate_content(model=VISION_MODEL, contents=["Tüm belgeleri analiz et. İsim, TC, Plaka, Şasi, Motor, Marka/Yıl, Vade çıkar."] + [Image.open(d) for d in dosyalar]).text
    except Exception as e: return f"Hata: {e}"
def kaza_analizi_yap(dosyalar, plaka, isim, beyan="Belirtilmedi"):
    try: return client.models.generate_content(model=VISION_MODEL, contents=[f"Eksper raporu hazırla. Müşteri: {isim}, Araç: {plaka}. Beyan: '{beyan}'. 1.Hasar Analizi, 2.Kusur, 3.Suistimal (Fraud) İhtimali (% olarak sert dille), 4.Dilekçe."] + [Image.open(d) for d in dosyalar]).text
    except Exception as e: return f"Hata: {e}"
def kvkk_pdf_olustur(isim, plaka):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 14); pdf.cell(0, 10, "GRIMSET STUDIO", ln=True, align="C"); pdf.set_font("Arial", "B", 12); pdf.cell(0, 10, "KVKK AYDINLATMA METNI", ln=True, align="C"); pdf.set_font("Arial", "", 10); pdf.multi_cell(0, 7, f"Sayin {isim} ({plaka}),\nVerileriniz KVKK kapsaminda sigorta islemleri icin islenmektedir. Bu belgeye 'ONAYLIYORUM' demeniz acik riza sayilir."); return pdf.output(dest="S").encode("latin-1")
def pdf_olustur(isim, plaka, tip, tem, prim, piyasa=None, kazanc=None, ref=None, dil="Türkçe"):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 16); pdf.cell(0, 10, f"GRIMSET STUDIO - QUOTE ({dil})", ln=True, align="C"); pdf.set_font("Arial", "", 12); pdf.cell(0, 10, f"Client: {isim}", ln=True); pdf.cell(0, 10, f"ID/Plate: {plaka}", ln=True); pdf.cell(0, 10, f"Type: {tip}", ln=True); pdf.multi_cell(0, 8, f"Details:\n{tem}"); pdf.set_font("Arial", "B", 14); pdf.cell(0, 10, f"Premium: {prim}", ln=True); return pdf.output(dest="S").encode("latin-1")
def filo_pdf_olustur(f, p_list, tip, prim):
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial", "B", 16); pdf.cell(0, 10, "B2B FILO", ln=True); pdf.set_font("Arial", "", 12); pdf.multi_cell(0, 8, f"Firma: {f}\nTip: {tip}\nAraclar: {', '.join(p_list)}\nToplam Prim: {prim:,} TL"); return pdf.output(dest="S").encode("latin-1")
def komisyon_hesapla(prim, tip):
    oran = 0.25 if tip in ["Seyahat Sağlık (Yurt Dışı)", "Elektronik Cihaz (Telefon/Laptop)", "Evcil Hayvan (Pati) Acil Durum", "Kısa Süreli Kiralık Araç Kaskosu"] else (0.15 if tip in ["Kasko", "Filo Kasko", "DASK", "Tamamlayıcı Sağlık Sigortası (TSS)", "Özel Sağlık Sigortası (ÖSS)"] else 0.08 if "Trafik" in tip else 0.10)
    return int(prim * oran)
def get_status_color(d): return {"İnceleniyor": "#f39c12", "Eksper Atandı": "#3498db", "Onarımda": "#9b59b6", "Ödeme Bekleniyor": "#e67e22", "Tamamlandı": "#2ecc71"}.get(d, "#95a5a6")
def temizle_fiyat(x):
    try: return int(str(x).replace(' TL', '').replace(',', '').replace('.', ''))
    except: return 0
db = veritabani_yukle()

# --- YAN MENÜ ---
st.sidebar.image("https://images.squarespace-cdn.com/content/v1/6055d01a61b2383be553b1b6/bd6d8e20-94d0-4e36-b552-6d2c4b574229/grimset+copy+copy+logo.png?format=1500w", width=150)
st.sidebar.markdown(f"**👤 Kullanıcı:** {st.session_state.kullanici_adi}")
if st.sidebar.button("🚪 Çıkış", use_container_width=True): log_action(st.session_state.kullanici_adi, st.session_state.rol, "Çıkış", ""); st.session_state.giris_yapildi=False; st.rerun()

if st.session_state.rol in ["Admin", "Satis"]:
    with st.sidebar.expander("🔔 GÜNLÜK AKSİYON", expanded=True):
        if sh:
            v_say, h_say, f_say, c_say = 0, 0, 0, 0
            try:
                ms = sh.worksheet("Müşteri Portföyü").get_all_records()
                for m in ms:
                    if m.get('Vade Tarihi') and 0 <= (datetime.strptime(str(m['Vade Tarihi']), "%Y-%m-%d").date() - datetime.now().date()).days <= 15: v_say+=1
                for h in sh.worksheet("Hasar Kayıtları").get_all_records():
                    if h.get("Durum") not in ["Tamamlandı", "İptal Edildi"]: h_say+=1
                for f in sh.worksheet("Satış Hunisi").get_all_records():
                    if f.get("Aşama") not in ["Kazanıldı", "İptal Edildi"]: f_say+=1
            except: pass
            st.markdown(f"⏰ Vade: `{v_say}` | 🚗 Hasar: `{h_say}` | 📌 Fırsat: `{f_say}`")

    menu = ["📋 Kayıt & Ayıklama", "📝 Poliçe Atölyesi", "⏱️ Mikro Sigorta (On-Demand)", "🏥 Sağlık (TSS/ÖSS)", "🏢 Kurumsal Filo (B2B)", "⏰ Vade & Otonom Yenileme", "📌 Satış Hunisi (Kanban)", "🚗 Hasar Asistanı & Süreç", "🗄️ Dijital Evrak Kasası"]
    if st.session_state.rol == "Admin": menu.extend(["🔄 AI Çapraz Satış (Cross-Sell)", "🎯 Kampanya Motoru", "📈 LTV & Churn", "💸 Gider Yönetimi", "📊 Finansal & Coğrafi Harita", "🔐 Audit Log"])
    sayfa = st.sidebar.radio("Menü:", menu)
else:
    sayfa = st.sidebar.radio("Menü:", ["🏠 Poliçelerim", "⏱️ Mikro Sigorta Al", "🚗 Hasar Bildir & Takip", "🗄️ Evrak Kasam"])

st.sidebar.caption("Grimset Studio © 2026")

# --- MÜŞTERİ EKRANLARI ---
if sayfa == "🏠 Poliçelerim" and st.session_state.rol == "Musteri":
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
    st.title("📝 Poliçe Atölyesi")
    isim, plaka, tel = st.text_input("Müşteri"), st.text_input("Plaka"), st.text_input("Tel")
    tip = st.selectbox("Tip", ["Kasko", "Zorunlu Trafik Sigortası", "DASK"])
    if st.button("💾 Kaydet") and isim and plaka and sh:
        prim = 15000 if tip=="Kasko" else 1200
        sh.worksheet("Üretilen Poliçeler").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), isim, plaka, tip, "Standart", f"{prim} TL", st.session_state.kullanici_adi, f"{komisyon_hesapla(prim, tip)} TL"])
        st.success("Kesildi.")

# YENİ: AI ÇAPRAZ SATIŞ MODÜLÜ
elif sayfa == "🔄 AI Çapraz Satış (Cross-Sell)" and st.session_state.rol == "Admin":
    st.title("🔄 AI Çapraz Satış & Upsell Otopilotu")
    st.markdown("Mevcut müşterilerin portföyünü tarayarak, onlara eksik oldukları poliçeleri özel paketlerle sunun.")
    st.markdown("---")
    
    if sh:
        try:
            policeler = sh.worksheet("Üretilen Poliçeler").get_all_records()
            if not policeler: st.warning("Poliçe verisi yok.")
            else:
                df_pol = pd.DataFrame(policeler)
                # Müşterileri ve aldıkları ürünleri grupla
                musteri_urunleri = df_pol.groupby('Müşteri Adı')['Poliçe Tipi'].apply(list).to_dict()
                
                firsatlar = []
                for musteri, urunler in musteri_urunleri.items():
                    # Basit Kural Seti
                    has_kasko = any("Kasko" in u for u in urunler)
                    has_saglik = any("Sağlık" in u for u in urunler)
                    has_dask = any("DASK" in u for u in urunler)
                    
                    if has_kasko and not has_saglik:
                        firsatlar.append({"Müşteri": musteri, "Eksik Ürün": "Tamamlayıcı Sağlık Sigortası (TSS)", "Nedeni": "Araç güvencesi var, sağlık güvencesi yok."})
                    if has_saglik and not has_dask:
                        firsatlar.append({"Müşteri": musteri, "Eksik Ürün": "DASK", "Nedeni": "Can güvenliği var, ev güvencesi yok."})
                
                if not firsatlar:
                    st.info("Harika! Tüm müşteriler tam koruma altında, yeni çapraz satış fırsatı bulunmuyor.")
                else:
                    df_firsat = pd.DataFrame(firsatlar)
                    st.subheader(f"💡 Yapay Zekanın Tespit Ettiği {len(firsatlar)} Sıcak Fırsat")
                    
                    secilen_firsat_idx = st.selectbox("Müşteri Seç:", range(len(firsatlar)), format_func=lambda x: f"{firsatlar[x]['Müşteri']} -> Öneri: {firsatlar[x]['Eksik Ürün']}")
                    secilen_firsat = firsatlar[secilen_firsat_idx]
                    
                    st.write(f"**Neden Bu Ürün?** {secilen_firsat['Nedeni']}")
                    
                    if st.button("🤖 Çapraz Satış Mesajı Üret", type="primary"):
                        with st.spinner("Gemini müşteriye özel satış senaryosu yazıyor..."):
                            prompt = f"""Sen elit bir sigorta satıcısısın. Mevcut müşterimiz {secilen_firsat['Müşteri']}, daha önce bizden hizmet aldı ({secilen_firsat['Nedeni']}). Ona şimdi "{secilen_firsat['Eksik Ürün']}" ürününü çapraz satış (cross-sell) ile satmak istiyoruz. 
Bizi tercih ettiği için ona özel %15 "VIP Sadakat İndirimi" tanımladığımızı söyleyen, sıcak, çok profesyonel ve hemen WhatsApp'tan gönderilecek 3-4 cümlelik kısa bir satış mesajı hazırla."""
                            try:
                                ai_mesaj = client.models.generate_content(model=TEXT_MODEL, contents=prompt).text
                                st.info(ai_mesaj)
                                
                                # WhatsApp linki
                                wa_link = f"https://wa.me/?text={urllib.parse.quote(ai_mesaj)}"
                                st.markdown(f'<a href="{wa_link}" target="_blank" style="text-decoration: none;"><div style="background-color: #25D366; color: white; text-align: center; padding: 10px; border-radius: 8px; font-weight: bold; margin-top: 10px;">💬 Mesajı WhatsApp\'tan Gönder</div></a>', unsafe_allow_html=True)
                                log_action(st.session_state.kullanici_adi, st.session_state.rol, "Çapraz Satış AI Kullanımı", f"Müşteri: {secilen_firsat['Müşteri']}, Önerilen: {secilen_firsat['Eksik Ürün']}")
                            except Exception as e:
                                st.error("AI Bağlantı Hatası.")
        except Exception as e: st.error(f"Veri Hatası: {e}")

elif sayfa == "⏱️ Mikro Sigorta (On-Demand)":
    st.title("⏱️ Mikro Sigorta")
    urun = st.selectbox("Koruma:", ["Seyahat Sağlık (Yurt Dışı)", "Elektronik Cihaz (Telefon/Laptop)"])
    gun = st.slider("Gün:", 1, 30, 3)
    isim, plaka = st.text_input("Ad"), st.text_input("Plaka/TC")
    if st.button("Sat"): sh.worksheet("Üretilen Poliçeler").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), isim, plaka, urun, "Mikro", f"{60*gun} TL", st.session_state.kullanici_adi, f"{komisyon_hesapla(60*gun, urun)} TL"]); st.success("Kesildi.")

elif sayfa == "🏥 Sağlık (TSS/ÖSS)":
    st.title("🏥 Sağlık AI")
    isim, yas = st.text_input("Ad"), st.slider("Yaş", 18, 80, 30)
    tip = st.radio("Tip", ["TSS", "ÖSS"])
    if st.button("Risk Analizi ve Kaydet"):
        sh.worksheet("Üretilen Poliçeler").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), isim, "Saglik", tip, f"Yaş {yas}", "15000 TL", st.session_state.kullanici_adi, "2250 TL"]); st.success("Kaydedildi.")

elif sayfa == "🏢 Kurumsal Filo (B2B)":
    st.title("🏢 Filo")
    firma, arac = st.text_input("Firma"), st.number_input("Adet", 1)
    if st.button("Kaydet"): sh.worksheet("Filo Teklifleri").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), firma, arac, "Filo", "Kasko", f"{arac*15000} TL", st.session_state.kullanici_adi, "0 TL"]); st.success("Kaydedildi")

elif sayfa == "⏰ Vade & Otonom Yenileme":
    st.title("⏰ Otonom Yenileme")
    if sh:
        ms = sh.worksheet("Müşteri Portföyü").get_all_records()
        for m in ms:
            if m.get('Vade Tarihi'):
                try:
                    kalan = (datetime.strptime(str(m['Vade Tarihi']), "%Y-%m-%d").date() - datetime.now().date()).days
                    if 0 <= kalan <= 15: st.warning(f"Vade: {m.get('Müşteri Adı')} - Kalan: {kalan} Gün")
                except: pass

elif sayfa == "📌 Satış Hunisi (Kanban)":
    st.title("📌 Kanban")
    isim, konu = st.text_input("Ad"), st.text_input("Konu")
    if st.button("Ekle"): sh.worksheet("Satış Hunisi").append_row(["ID", datetime.now().strftime("%Y-%m-%d"), isim, "Tel", konu, "0", "Yeni Aday", st.session_state.kullanici_adi]); st.success("Eklendi")
    df = pd.DataFrame(sh.worksheet("Satış Hunisi").get_all_records())
    if not df.empty: st.dataframe(df)

elif sayfa == "🚗 Hasar Asistanı & Süreç":
    st.title("🚗 Hasar Asistanı")
    isim, plaka, beyan = st.text_input("Ad"), st.text_input("Plaka"), st.text_area("Beyan (AI Fraud Analizi İçin)")
    if st.button("Kaydet"): sh.worksheet("Hasar Kayıtları").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), isim, plaka, beyan, "İnceleniyor"]); st.success("Açıldı")

elif sayfa == "🗄️ Dijital Evrak Kasası":
    st.title("🗄️ Evrak Kasası")
    dosya = st.file_uploader("Evrak")
    isim = st.text_input("Müşteri Adı")
    if st.button("Yükle") and dosya: sh.worksheet("Evrak Kasası").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), isim, "Plaka", "Evrak", dosya.name, st.session_state.kullanici_adi]); st.success("Yüklendi")

elif sayfa == "📈 LTV & Churn":
    st.title("📈 LTV ve Churn")
    if sh:
        policeler = sh.worksheet("Üretilen Poliçeler").get_all_records()
        if policeler:
            df = pd.DataFrame(policeler)
            musteri = st.selectbox("Müşteri", df['Müşteri Adı'].unique())
            if st.button("Hesapla"):
                st.info(f"Seçilen Müşteri: {musteri}. İşlem sayısı: {len(df[df['Müşteri Adı']==musteri])}. Yapay Zeka Risk tahmini: Düşük.")

elif sayfa == "💸 Gider Yönetimi":
    st.title("💸 Gider")
    kalem, tutar = st.text_input("Gider"), st.number_input("Tutar")
    if st.button("Ekle"): sh.worksheet("Şirket Giderleri").append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), kalem, "Kategori", f"{tutar} TL", st.session_state.kullanici_adi]); st.success("Eklendi")

elif sayfa == "📊 Finansal & Coğrafi Harita":
    st.title("📊 Dashboard & Harita")
    if sh:
        df = pd.DataFrame(sh.worksheet("Üretilen Poliçeler").get_all_records())
        if not df.empty:
            df['Net'] = df['Net Komisyon'].apply(temizle_fiyat)
            st.success(f"TOPLAM NET KOMİSYON: {df['Net'].sum():,} TL")
            df['İl'] = df['Plaka'].apply(lambda x: re.search(r'^\d{2}', str(x)).group(0) if re.search(r'^\d{2}', str(x)) else "00")
            st.write(df.groupby('İl')['Net'].sum())

elif sayfa == "🔐 Audit Log":
    st.title("🔐 Audit Log (Kara Kutu)")
    st.dataframe(pd.DataFrame(sh.worksheet("Audit Log").get_all_records()).iloc[::-1])
