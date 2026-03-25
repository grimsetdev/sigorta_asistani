import os
import math
import pickle
import streamlit as st
from pypdf import PdfReader
from google import genai
from PIL import Image

# --- Sayfa Ayarları ---
st.set_page_config(page_title="Grimset AI | Sigorta Otomasyonu", page_icon="🛡️", layout="wide")

# Gemini 2.0 Flash modeli görüntü işleme için mükemmeldir
client = genai.Client()
VISION_MODEL = 'gemini-2.5-flash'
TEXT_MODEL = 'gemini-2.5-flash'

HAFIZA_DOSYASI = "vektor_hafizasi.pkl"
BELGELER_KLASORU = "belgeler"

# --- Arka Plan Fonksiyonları (Vektör & OCR) ---

def metni_vektore_cevir(metin):
    # En güncel embedding modeli
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
    # Eski PDF okuma mantığı (Değişmedi, performansı arttırıldı)
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
    # Yükleme ekranı
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
    """
    Gemini Vision modelini kullanarak ruhsat görselinden veri ayıklar.
    """
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

# Veritabanını Başlat
db = veritabani_yukle()

# --- WEB ARAYÜZÜ (UI) BAŞLANGICI ---

# Sayfa Düzeni (Sol panel & Sağ panel)
sol_panel, sag_panel = st.columns([1, 2], gap="large")

with sol_panel:
    st.image("https://images.squarespace-cdn.com/content/v1/6055d01a61b2383be553b1b6/bd6d8e20-94d0-4e36-b552-6d2c4b574229/grimset+copy+copy+logo.png?format=1500w", width=200) # Grimset logo (örnek)
    st.title("🛡️ Sigorta Otomasyonu")
    st.markdown("---")
    
    st.subheader("📷 Ruhsat/Evrak Okuma")
    st.write("Müşteriden gelen ruhsat fotoğrafını yükleyin, verileri anında ayıklayalım.")
    
    yuklenen_gorsel = st.file_uploader("Ruhsat fotoğrafı yükle...", type=["jpg", "jpeg", "png"])
    
    if yuklenen_gorsel:
        st.image(yuklenen_gorsel, caption="Yüklenen Görsel", use_container_width=True)
        
        if st.button("Verileri Ayıkla 🚀", use_container_width=True):
            with st.spinner("Gemini Vision çalışıyor..."):
                ayiklanan_veri = ruhsat_oku(yuklenen_gorsel)
                if ayiklanan_veri:
                    st.success("Veriler Ayıklandı!")
                    # Veriyi kopyalanabilir bir alanda göster
                    st.text_area("Ayıklanan Bilgiler (Teklif ekranına kopyalayın)", value=ayiklanan_veri, height=250)
                    
    st.markdown("---")
    st.info("İpucu: Mevzuat sorularını sağdaki sohbet panelinden sorun.")

with sag_panel:
    st.subheader("💬 Mevzuat & Poliçe Sohbeti")
    
    # Sohbet geçmişini tutmak için session_state kullanımı
    if "mesajlar" not in st.session_state:
        st.session_state.mesajlar = []

    # Eski mesajları ekrana çizdir
    for mesaj in st.session_state.mesajlar:
        with st.chat_message(mesaj["rol"]):
            st.markdown(mesaj["icerik"])

    # Kullanıcıdan yeni soru al
    if soru := st.chat_input("Sigorta poliçesi hakkında bir soru sorun..."):
        # Kullanıcı mesajını ekrana ekle
        st.session_state.mesajlar.append({"rol": "user", "icerik": soru})
        with st.chat_message("user"):
            st.markdown(soru)

        # Asistanın düşünüp cevap vermesi
        with st.chat_message("assistant"):
            with st.spinner("Mevzuat taranıyor..."):
                soru_vektoru = metni_vektore_cevir(soru)
                skorlar = []
                for item in db:
                    skor = benzerlik_hesapla(soru_vektoru, item["vektor"])
                    skorlar.append((skor, item["metin"]))
                
                skorlar.sort(key=lambda x: x[0], reverse=True)
                en_iyi_parcalar = [metin for skor, metin in skorlar[:5]]
                baglam = "\n---\n".join(en_iyi_parcalar)
                
                prompt = f"Sen uzman bir sigorta danışmanısın.\nSoruları SADECE aşağıdaki bağlamdaki bilgilere dayanarak yanıtla. Hangi kaynaktan (örn: Kasko, DASK) faydalandığını belirt.\nEğer cevap bağlamda yoksa 'Elimdeki mevzuatta net bilgi yok' de ve uydurma.\n\nBağlam:\n{baglam}\n\nSoru: {soru}"

                response = client.models.generate_content(
                    model=TEXT_MODEL,
                    contents=prompt
                )
                
                st.markdown(response.text)
                st.session_state.mesajlar.append({"rol": "assistant", "icerik": response.text})