MAHZEN • FEDYA — RENDER KURULUMU

DOSYALAR
- app.py: Discord botu + halka açık dashboard + Fedya AI entegrasyonu
- requirements.txt: Python paketleri
- render.yaml: Render Blueprint ayarları

RENDER'A YÜKLEME
1. Bu dosyaları bir GitHub deposuna yükle.
2. Render hesabında New + > Blueprint seç ve GitHub deposunu bağla.
3. render.yaml dosyasını algıladığında servisi oluştur.
4. DISCORD_TOKEN alanına Discord Developer Portal'daki bot tokenını gir.
5. OPENROUTER_API_KEY alanına OpenRouter anahtarını gir. Anahtarı Discord'a, sohbete veya koda yazma.
6. Deploy tamamlanınca Render'ın verdiği https://...onrender.com adresi dashboard olur. /health adresi {"ok":true,...} döndürür.

AI
- Varsayılan model: openrouter/free. Ücretsiz model yönlendirmesi kullanılabilir; sağlayıcı limitleri ve erişilebilir modeller değişebilir.
- İstersen Render Environment bölümünden AI_MODEL değerini başka bir OpenRouter modeline değiştirebilirsin.
- API anahtarı ayarlanmamışsa Fedya gerçek AI cevabı vermez; anahtarın eklenmesi gerekir.

ÖNEMLİ SINIRLAMALAR
- Dashboard şifresiz ve salt-okunur: etkinlik/anket verilerini herkes görebilir; buradan yönetim işlemi yapılmaz.
- Render Free web servisleri boşta kaldığında uykuya geçebilir. Bu, Discord botunun sürekli çevrimiçi kalmasını garanti etmez. Sürekli çalışan bot için Render'da daima açık ücretli servis veya ayrı bir always-on bot hostu gerekir.
- Free servislerin dosya sistemi kalıcı değildir. Yeniden dağıtım/yeniden başlatmada SQLite verisi kaybolabilir. Kalıcı veri için Render persistent disk (ücretli plan gerektirebilir) veya PostgreSQL entegrasyonu eklenmelidir.
- Bu ortamdan senin Render/GitHub hesabına giriş yapıp yayına alma işlemini gerçekleştiremiyorum; proje dağıtıma hazırlandı ama herkese açık canlı URL'yi Render oluşturduktan sonra alırsın.

GÜVENLİK
- Tokenı asla app.py içine yapıştırıp GitHub'a gönderme; Render Environment alanını kullan.
- Dashboard public olduğu için özel/kişisel bilgileri veritabanına koyma.
