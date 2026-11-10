# NEXUS-HW — Türkçe Hızlı Başlangıç

NEXUS-HW v0.7.0, yetkili ve izole laboratuvar hedefleri için hazırlanmış C++20 tabanlı bir UART/SPI/I²C greybox protokol fuzzing araştırma prototipidir.

## Bu sürümde neler var?

- C++20 sabit boyutlu çekirdek; fuzz yürütme yolunda dinamik bellek tahsisi yoktur.
- ESP32-S3 üzerinde Core 1'de payload mutasyonu, Core 0'da bus I/O yapan statik FreeRTOS görevleri.
- UART, SPI ve I²C adaptörleri; bir derlemede bir arayüz seçilir.
- ACK/NACK/device error/timeout yanıt sınıflandırması.
- Yanıt fingerprint'lerinden gözlemlenebilir durum düğümleri ve geçiş grafiği.
- Kalibrasyon ortalaması ve standart sapmasına göre zamanlama anomalisi adayı işaretleme.
- Üç ardışık timeout/bus hatasında güvenli heartbeat ile hedef liveness doğrulaması.
- Hedef Alive / Degraded / Unresponsive / LinkFault sınıflandırması.
- Crash-suspected olay günlüğü: tetikleyici frame, case ID, komut etiketi, gecikme ve başarısız heartbeat sayısı sabit boyutlu RAM kaydında tutulur.
- Güvenli opcode survey: gerçek donanımda yalnızca operatörün belgeleyip read-only olarak işaretlediği komut manifesti test edilir.
- Host simülatöründe 0x00–0xFF tam opcode sweep demosu; fiziksel bus'a bağlanmaz.
- Host üzerinde corpus keşfi ve gözlemlenebilir yanıt fingerprint'lerine göre corpus minimizasyonu; çıktı C++ header olarak dışa aktarılır.
- Crash triage aracı: ESP-IDF/Xtensa panik günlükleri ve Cortex-M fault snapshot'larından register/backtrace çıkarımı, ELF ile `addr2line` sembolleştirmesi ve kanıta dayalı azaltım önerileri.
- Ayrı debug UART / fault logları ile tetikleyici fuzz frame'ini bir araya getiren ayrıntılı crash inceleme iş akışı.

- GDB/OpenOCD entegrasyonu: canlı GDB server veya offline core dosyasından register, thread/backtrace, frame/local, PC disassembly ve stack dump yakalama; doğrudan HTML crash dashboard üretimi.
- ESP32-S3 ve RP2040 için ayrı debug-symbol PlatformIO profilleri (`esp32s3-debug`, `rpipico-debug`).
- Crash minimization sırasında protokol checksum yeniden hesaplama (XOR8, SUM8, CRC-8/MAXIM, CRC-16/CCITT-FALSE, CRC-16/MODBUS, CRC-32/IEEE ve parametreli custom CRC); checksum tanımlandığında frame uzunluğu korunur.
- Tekrarlı oracle/quorum doğrulaması ile kararsız crash sonuçlarının azaltılması.
- Release + ASan/UBSan doğrulama matrisi ve warnings-as-errors derlemesi.
- Coverage-guided campaign scheduler: sabit boyutlu corpus, deterministik seed seçimi, target binary coverage ve protokol geçiş coverage'ı için ayrılmış 3072-bit feedback map.
- ESP32-S3 üzerinde Core 1 producer / Core 0 consumer arasında case-by-case feedback handshake; target coverage gelmeden sonraki seed seçilmez.
- İki yönlü target diagnostic sideband: `NXCOV_BEGIN,<case_id>` ile vaka korelasyonu ve `NXCOV1` ile aynı vakaya ait 2048-bit hedef coverage bitmap'i.
- RP2040'da aynı sabit bellek campaign scheduler ve gözlemlenebilir protokol geçiş feedback'i. Bu sürüm Pico'da gerçek target binary coverage iddiasında bulunmaz.
- JSONL campaign kayıtları ve çevrimdışı interaktif HTML campaign dashboard'u.
- JSON protocol manifest compiler: doğrulanmış salt-okunur komut tanımlarından C++ corpus/profile header üretimi.

## Linux üzerinde derle ve test et

Gereksinimler: CMake 3.20+ ve C++20 destekleyen bir derleyici.

```bash
./scripts/build_native.sh
./build/nexus_sim
```

`nexus_sim`, gerçek donanıma bağlanmaz; örnek/fiktif bir hedefi bilgisayarda simüle eder.

## 1) Host üzerinde simülasyon ve corpus optimizasyonu

```bash
./scripts/build_native.sh
./build/nexus_sim --host-optimize 4096 optimized_corpus.hpp
```

Komut, yalnızca yerel ve kurgusal protokol modeli üzerinde mutasyon yapar; yeni yanıt fingerprint'leri için ilk örnek girdileri saklar ve `optimized_corpus.hpp` üretir. Bu sonuç gerçek cihaz davranışının simülasyonu değildir. Her girdiyi gerçek hedefin dokümantasyonuna göre incelemeden donanıma aktarma.

## 2) ESP32-S3 firmware derlemesi

PlatformIO Core kurulduktan sonra proje kökünde:

```bash
pio run -e esp32s3
```

Firmware varsayılan olarak **DISARMED** gelir. Yalnızca kendi cihazın veya yazılı izinli, elektriksel olarak izole edilmiş laboratuvar düzeneğin için `platformio.ini` içinde şu iki bayrağı aç:

```ini
-DNEXUS_AUTHORIZED_LAB_TARGET=1
-DNEXUS_ACTIVE_FUZZ_ENABLED=1
```

Arayüz seçimi:

```ini
-DNEXUS_LINK_MODE=1   ; UART
-DNEXUS_LINK_MODE=2   ; SPI
-DNEXUS_LINK_MODE=3   ; I2C
```

Aynı anda yalnızca bir link modu seç. Pinleri ve hedef protokol parametrelerini gerçek kartının şeması ve hedef cihazın datasheet'i ile doğrula. Örnek pinler tüm ESP32-S3 kartları için garanti değildir.

## 3) Corpus nasıl düzenlenir?

`examples/lab_corpus.hpp` dosyasındaki corpus tamamen örnektir. Her girişte:

- `frame`: dokümantasyondan alınmış veya laboratuvarda doğrulanmış güvenli istek çerçevesi.
- `immutable_prefix`: opcode/adres/komut seçici gibi değişmemesi gereken ilk baytların sayısı.
- `minimum_mutable_bytes`: fuzz edilebilir payload'ın asgari uzunluğu.
- `command_tag`: raporda görülen yerel komut etiketi.

Mutator yalnızca `immutable_prefix` sonrasındaki payload baytlarını değiştirir; frame uzunluğunu ve komut önekini korur. `CorpusEntry::checksum` etkinleştirilirse tanımlı veri aralığı mutate edilir ve checksum alanı her mutasyondan sonra yeniden hesaplanır. Desteklenen algoritma ve alan yerleşimi için §12'ye bak.

## 4) Hedef çökmesi mi, yalnızca yanıt vermeyen komut mu?

`EngineConfig::liveness` alanına hedefin belgelenmiş, salt-okunur bir status/identity isteğini ve beklenen yanıt imzasını tanımla. Varsayılan ESP32-S3 örneği corpus'un ilk salt-okunur status isteğini heartbeat olarak kullanır.

- Tek bir fuzz isteği timeout verirse hedef hemen çökmüş sayılmaz; hata serisi izlenir.
- `max_consecutive_io_errors` eşiğinde NEXUS-HW heartbeat isteğini `retries` kadar dener.
- Heartbeat beklenen imzayı döndürürse `Alive`: fuzz isteği reddedilmiş/yok sayılmış/uygulama katmanında timeout olmuş olabilir; test devam eder.
- Beklenmeyen fakat boş olmayan yanıt gelirse `Degraded`: hedef cevap veriyor ama protokol imzası beklenenden farklıdır.
- Tüm heartbeat denemeleri timeout olursa `Unresponsive`: araç `CRASH_SUSPECTED` kaydı oluşturur ve güvenli biçimde durur.
- Bus error ağırlıklı heartbeat başarısızlığında `LinkFault` raporlanır.

`CRASH_SUSPECTED` gerçek MCU çökmesinin matematiksel kanıtı değildir: aynı gözlem kopuk kablo, kilitli bus, güç sorunu veya hedefin askıda kalmasıyla da oluşabilir. Kesin ayrım için bağımsız reset/status GPIO, akım ölçümü, UART boot logu veya fiziksel gözlem gibi ikinci bir tanılama kanalı gerekir. NEXUS-HW hedefi otomatik resetlemez veya güç döngüsüne sokmaz. Tetikleyen fuzz frame'i ve metadata'sı crash ring-buffer'a kaydedilir.

## 5) Opcode kapsamı

Fiziksel donanımdaki `SafeOpcodeSurvey`, yalnızca `documented_read_only=true` olarak işaretlenen, operatör tarafından gözden geçirilmiş komut çerçevelerini test eder. Bilinmeyen opcode aralığını veya gizli backdoor/service-mode unlock dizilerini gerçek cihaza brute-force etmez. Manifestteki her komut için Accepted / Rejected / DeviceError / NoResponse / TransportFault ve yanıt fingerprint'i raporlanır. İsteğe bağlı firmware derleme anahtarı `NEXUS_ENABLE_SAFE_OPCODE_SURVEY=1`'dir.

Tam 256 opcode enumerasyonu yalnızca yerel, kurgusal host simülatöründedir:

```bash
./build/nexus_sim --opcode-sweep-sim
```

Bu mod gerçek UART/SPI/I²C adaptörlerini kullanmaz; simüle edilmiş salt-okunur 0xD3 status opcode'unu bulur. Gerçek hedefte keşif çalışması için üretici dokümantasyonu, yazılı izin ve açıkça güvenli olarak tanımlanmış bir komut manifesti gerekir.

## 6) Güvenlik sınırları

Bu sürüm gerçek donanımda bilinmeyen opcode'ları veya gizli servis/backdoor unlock dizilerini brute-force etmez. Fiziksel opcode survey sadece operatörün doğruladığı salt-okunur manifest girdilerini çalıştırır. Unlock, bootloader, erase, program, reset, aktüatör veya safety-control komutları tarama kapsamına alınmaz. Fuzzer, operatörün corpus'undaki onaylı komutların payload alanını mutate eder.

ESP32-S3 GPIO pinleri 5 V toleranslı değildir. Seviye dönüştürücü, ortak GND, uygun pull-up, akım sınırlama ve fiziksel acil ayırma kullan. Canlı PLC, şebeke elektriği, araca bağlı ECU, üretim router'ı veya devredeki sayaç üzerinde deneme yapma.

## 7) Ayrıntılı crash teşhisi ve mevcut sınırlamalar

- Bu pakette ESP32-S3 ve RP2040/Pico için ayrı PlatformIO firmware hedefleri bulunur; ikisi de fiziksel kartta ayrıca doğrulanmalıdır.
- UART yanıt sonlandırması 1.5 ms boşluk varsayar.
- SPI sabit uzunluklu full-duplex işlem uygular.
- I²C sabit konfigüre edilmiş adrese yazar ve ayarlı miktarda yanıt ister; bus scan yapmaz.
- Durum çıkarımı cihazın iç RAM durumunu değil, dışarıdan gözlemlenebilen yanıt fingerprint'lerini temsil eder.
- Timing alert bir adaydır; tek başına side-channel kanıtı değildir.
- Heartbeat yokluğu yalnızca `Unresponsive/Crash Suspected` sonucunu destekler; kablo/bus arızasıyla gerçek firmware crash'i bağımsız kanıt olmadan kesin ayrılamaz.
- Tam kaynak satırına inmek için hedefin panic/fault logu ve tam olarak aynı build'e ait ELF gerekir. NEXUS, yalnızca bus gözleminden CPU'nun hangi talimatta çöktüğünü bilemez.
- `tools/nexus_triage.py` ESP-IDF/Xtensa panic, Cortex-M fault, ASan ve UBSan günlüklerini sınıflandırır; PC/backtrace adreslerini veya doğrudan sanitizer satırlarını çıkarır, uygun `addr2line` aracıyla sembolleştirir ve stack/heap/pointer/bus fault türüne göre savunma önerileri üretir. Ayrıntı: `docs/CRASH_DIAGNOSTICS.md`.
- İsteğe bağlı iki yönlü hedef tanılama UART'ı: `platformio.ini` içinde `NEXUS_TARGET_DIAG_UART_ENABLED=1` yap; `NEXUS_TARGET_DIAG_RX_PIN` ve `NEXUS_TARGET_DIAG_TX_PIN` değerlerini kartına göre seç. Sadece log yakalama için `NEXUS_TARGET_COV_SYNC_ENABLED=0` bırak; gerçek case-coverage senkronizasyonu için ayrıca `NEXUS_TARGET_COV_SYNC_ENABLED=1` aç. NEXUS TX → hedef RX ve hedef TX → NEXUS RX bağlantılarını uygun seviye dönüştürme/izolasyonla, fuzz bus'ından ayrı kur. Her fuzz case öncesi NEXUS `NXCOV_BEGIN,<case_id>` gönderir; hedefte `TargetCoverageSession::poll_begin()` bunu alır, coverage bitmap'ini sıfırlar; istek dispatch edildikten sonra `emit_after_case()` aynı case ID ile `NXCOV1` üretir. Seri konsolu `pio device monitor -b 115200 | tee nexus-run.log` ile kaydet.
- Host corpus optimizasyonu: `docs/HOST_SIMULATION.md`.
- Native çekirdek ve Python araçları doğrulandı. Bu çalışma ortamında PlatformIO ve hedef cross-toolchain bulunmadığından ESP32-S3/RP2040 firmware derlemesi ve fiziksel kart testi yapılmadı.

## v0.4.0 — Reverse-engineering diagnostics, coverage, minimization, checksums, RP2040

### 8) Ayrıntılı crash/binary analysis raporu (HTML)

NEXUS-HW artık panic/fault logu, NEXUS tetikleyici girdisi ve aynı build'e ait ELF/MAP verilerini tek bir çevrimdışı raporda birleştirir. HTML raporu disassembler/debugger tarzı panellerle sunulur:

- Fault sınıfı, güven düzeyi ve ham kanıt satırları.
- Xtensa A-register'ları veya Cortex-M R0-R12, SP/MSP/PSP, LR, PC, xPSR ve mevcut fault-status register'ları.
- Fault PC ve backtrace adresleri.
- ELF architecture/class, GNU Build ID, `.text/.rodata/.data/.bss` bölümleri ve LOAD segmentleri.
- Mimariye uygun `addr2line` ile fonksiyon/kaynak satırı eşlemesi ve `--source-root` ile satır çevresinin Source View panelinde gösterilmesi.
- Mimariye uygun `objdump` ile PC etrafındaki assembly/disassembly; CPU register, stack memory, task/core context ve ELF section/load map panelleri.
- Linker MAP dosyasındaki ilgili adres satırları.
- Coverage özeti, NEXUS case ID ve tetikleyici paket.
- Hata sınıfına göre azaltım / düzeltme önerileri ve kanıt eksikleri.

Örnek:

```bash
python3 tools/nexus_triage.py \\
  --input captures/nexus-target-combined.log \\
  --elf build/target.elf \\
  --map build/target.map \\
  --coverage build/coverage-report.json \\
  --format html \\
  --output reports/crash-analysis.html
```

ESP32-S3 için ELF ile aynı ESP-IDF/PlatformIO Xtensa toolchain'inin `xtensa-esp32s3-elf-addr2line`, `xtensa-esp32s3-elf-objdump` ve `xtensa-esp32s3-elf-readelf` araçlarını; RP2040 için `arm-none-eabi-addr2line`, `arm-none-eabi-objdump` ve `arm-none-eabi-readelf` araçlarını kullan. Araçlar PATH üzerinde değilse `--addr2line`, `--objdump`, `--readelf` ile tam yol ver.

**Build kimliğini çıkar:**

```bash
python3 tools/nexus_build_info.py --elf .pio/build/esp32s3/firmware.elf --output build-info.json
```

Komut ELF Build ID ve SHA-256 değerini verir. `BUILD_ID=<id>` satırını hedef loguna ekleyerek aynı firmware görüntüsüyle eşleşmeyi doğrula. `--source-root` parametresiyle aynı kaynak revision'ını ver:

```bash
python3 tools/nexus_triage.py --input captures/nexus-target-combined.log \
  --elf .pio/build/esp32s3/firmware.elf --map .pio/build/esp32s3/firmware.map \
  --source-root ./target-firmware --format html --output reports/debugger-view.html
```

**Build eşleşmesi:** PlatformIO ortamlarında ELF GNU Build ID ve linker map üretimi için `-Wl,--build-id=sha1` ve `-Wl,-Map=firmware.map` eklenmiştir. Log içinde `BUILD_ID=<id>` varsa NEXUS, ELF Build ID ile karşılaştırır. ID'ler uyuşmazsa yanlış kaynak satırı göstermemek için symbolication/disassembly işlemini durdurur. ELF, MAP, source revision ve flashed firmware aynı derlemeye ait tutulmalıdır.

> Sadece UART/SPI/I²C timeout'u PC veya kaynak satırı vermez. ESP32 panic konsolu, RP2040 fault snapshot'ı veya Cortex-M fault register dump'ı gereklidir. Rapor kanıt yokken crash adresi uydurmaz.

### 9) RP2040 / Raspberry Pi Pico

PlatformIO ortamı eklendi:

```bash
pio run -e rpipico
pio run -e rpipico -t upload
pio device monitor -b 115200
```

Pico pinleri `platformio.ini` / `rp2040_main.cpp` varsayılanlarında örnektir; kullandığın kartın pinout'una göre doğrula. `NEXUS_LINK_MODE=1/2/3` UART/SPI/I²C seçer. ESP32-S3 gibi Pico firmware de **DISARMED** derlenir; iki yetkilendirme bayrağı varsayılan olarak `0` kalır. RP2040 sürümü taşınabilirlik için kooperatif tek döngü yürütücüsü kullanır; ESP32-S3'ün sabitlenmiş FreeRTOS dual-core task modelini RP2040'a kopyalamaz.

RP2040 Cortex-M0+ için isteğe bağlı hedef fault hook örneği `examples/target_hooks/rp2040_hardfault_capture.cpp` konumundadır. Bu hook HardFault exception stack frame'indeki R0-R3, R12, LR, PC ve xPSR değerlerini `.noinit` SRAM alanına yazar. Hedefi manuel olarak resetledikten sonra `nexus_rp2040_print_fault_snapshot(Serial)` çağrısıyla kayıt seri porta aktarılabilir. Cortex-M0+ üzerinde Cortex-M3/M4'e özgü CFSR/BFAR register'ları bulunmadığından hook bunları taklit etmez. Bu dosya hedef firmware'e operatör tarafından eklenir; fuzzer firmware'ine otomatik dahil edilmez.

### 10) Gerçek hedef firmware code coverage

`include/nexus/coverage.hpp` sabit boyutlu, atomik edge bitmap sağlar. Hedef firmware'in test derlemesinde, sahibi olduğun / instrument etmeye yetkili olduğun parser ve state-machine temel bloklarına kararlı ID'lerle `NEXUS_COV_HIT(edge_id)` ekle. Varsayılan bitmap 2048 edge ID'si tutar (0–2047).

Hedef firmware'de coverage raporu üret:

```cpp
#include "nexus/coverage.hpp"

// Parser/state-machine içindeki anlamlı kontrol akışlarına ekle:
NEXUS_COV_HIT(17); // stable edge ID 17

// Test case sonu veya güvenli snapshot noktasında:
char record[600]{};
if (nexus::g_nexus_coverage.format_record(record, sizeof(record), case_id)) {
    Serial.println(record); // USB/debug UART üzerinden host'a aktar
}
```

Örnek hedef entegrasyonu `examples/instrumented_target/coverage_example.cpp` içindedir. NEXUS ESP32-S3 tarafındaki ayrı diagnostic UART satırlarını `TARGET_LOG` önekiyle ana seri kayda aktarabilir. RP2040'da hedef debug konsolunu ayrı bir USB-UART adaptörüyle kaydet ve NEXUS kaydıyla birleştir.

Coverage raporu:

```bash
python3 tools/nexus_cov.py \\
  --input captures/combined-run.log \\
  --total-edges 128 \\
  --output reports/coverage-report.json
```

`--total-edges`, hedefin instrumentation map'inde atanan toplam edge ID sayısıdır. Verilmezse araç bulunan unique edge sayısını raporlar ancak yüzde uydurmaz. Birden fazla `NXCOV1` satırı birleştirilir; her run için o ana kadar görülmemiş edge sayısı çıkarılır.

**Kapsam sınırı:** Bu, gerçek hedef firmware'in çalıştırdığı ve `NEXUS_COV_HIT` ile işaretlenmiş kod yollarının coverage'ıdır. Kapalı bir firmware'in keyfi makine kodundan otomatik basic-block coverage çıkarmaz. Bunun için hedefe uygun compiler instrumentation / debugger trace veya kaynak seviyesinde hook gerekir. Host simulator response-state novelty bilgisi gerçek target code coverage olarak raporlanmaz.

### 11) Crash-inducing input minimization

`tools/nexus_minimize.py` delta-debugging ile crash'i koruyan en küçük girdiyi arar. Test tekrarını operatörün verdiği oracle komutu yönetir; komut shell üzerinden değil, tokenize edilerek çalıştırılır. `{input}` geçici binary dosyanın yoludur.

```bash
python3 tools/nexus_minimize.py \\
  --input crashes/original.bin \\
  --output crashes/minimized.bin \\
  --immutable-prefix 1 \\
  --oracle-command 'python3 my_lab_replay.py --input {input}' \\
  --crash-regex 'Guru Meditation|HardFault|AddressSanitizer|CRASH_CONFIRMED' \\
  --report crashes/minimized.json
```

Oracle, aynı fault sınıfını doğrulayan hedef logunu üretmelidir. Varsayılan regex genel panic/fault imzalarını yakalar; cihazına göre daha spesifik bir regex belirle. `CRASH_SUSPECTED` tek başına kesin crash oracle'ı sayılmamalıdır. Araç her adayın tekrarını oracle'a sorar, sabit prefix'i silmez ve final girdisini bir kez daha doğrular. Fiziksel hedefte replay script'inin güç/reset prosedürünü ve hız sınırını kendin tanımla; minimizer hedefi otomatik power-cycle etmez.

Yerel örnek oracle:

```bash
python3 tools/nexus_minimize.py \\
  --input examples/corpus/crash-demo.bin \\
  --output /tmp/minimized.bin \\
  --immutable-prefix 1 \\
  --oracle-command 'python3 examples/oracles/demo_crash_oracle.py --input {input}' \\
  --report /tmp/minimized.json
```

### 12) Protokol checksum motoru

`CorpusEntry::checksum` etkinleştirildiğinde mutator payload'ı değiştirdikten sonra tanımlı checksum alanını yeniden hesaplar. Böylece checksum'ı doğru kalan mutasyonlar yapılabilir. Desteklenen algoritmalar:

- XOR8 ve SUM8
- CRC-8/MAXIM
- CRC-16/CCITT-FALSE
- CRC-16/MODBUS
- CRC-32/IEEE
- Özel CRC-8/16/32 polinomu, başlangıç değeri, xor-out ve input/output reflection ayarları

Örnek yapılandırma:

```cpp
entry.checksum.enabled = true;
entry.checksum.algorithm = nexus::ChecksumAlgorithm::Crc16Modbus;
entry.checksum.data_offset = 1;       // checksum hesabının başladığı byte
entry.checksum.data_length = 4;       // kapsanan byte sayısı
entry.checksum.checksum_offset = 5;  // CRC alanı
entry.checksum.big_endian = false;   // Modbus low byte first

// Özel CRC kullanımı örneği:
entry.checksum.algorithm = nexus::ChecksumAlgorithm::Crc16Custom;
entry.checksum.polynomial = 0x1021;
entry.checksum.initial = 0xFFFF;
entry.checksum.xor_out = 0xFFFF;
entry.checksum.reflect_input = true;
entry.checksum.reflect_output = true;
```

Checksum alanı frame içindeki ayrı bir byte aralığıdır; checksum motoru veri aralığı ile checksum alanının çakışmasını reddeder. Alanın trailing olması zorunlu değildir; `checksum_offset` gerçek protokol yerleşimine göre ayarlanır. Algoritma, aralık, offset, başlangıç değeri veya endian protokole özel ise manifestini gerçek cihaz dokümantasyonuna göre yapılandır; örnek değerleri körlemesine kopyalama. Mutator checksum alanını payload olarak mutate etmez.

## v0.4.0 doğrulama durumu (önceki sürüm)

- Native C++20 Release build ve CTest: 4/4 test paketi PASS.
- ASan + UBSan Debug build ve CTest: 4/4 test paketi PASS.
- ELF build-ID kontrolü, addr2line sembolleştirme, source excerpt, objdump disassembly ve linker-map eşlemesi geçici bir native ELF fixture üzerinde doğrulandı.
- Coverage parser örnek kayıtta 16 instrument edilmiş edge içinden 3 benzersiz edge (%18.75) raporladı.
- Crash minimizer CLI örneği 36 baytı 20 bayta indirdi ve demo oracle ile aynı örnek imzayı yeniden üretti; 10 denemelik bu örnek global minimum iddiası taşımaz.
- PlatformIO bu çalışma ortamında kurulu olmadığından ESP32-S3/RP2040 firmware derlemesi, upload ve fiziksel kart doğrulaması yapılmadı.


## 12) GDB / OpenOCD canlı ve offline debugger entegrasyonu

Debug sembollü firmware derle:

```bash
pio run -e esp32s3-debug
# veya
pio run -e rpipico-debug
```

OpenOCD'yi uygun debug arayüzüyle ayrı terminalde başlat:

```bash
# ESP32-S3: JTAG kullanır, SWD desteklemez
openocd -f board/esp32s3-builtin.cfg

# RP2040: CMSIS-DAP Debug Probe üzerinden SWD
openocd -f interface/cmsis-dap.cfg -f target/rp2040.cfg
```

Canlı GDB yakalama ve HTML raporu:

```bash
python3 tools/nexus_debug.py --profile rp2040 \
  --elf .pio/build/rpipico-debug/firmware.elf \
  --gdb arm-none-eabi-gdb --remote localhost:3333 --halt \
  --capture captures/pico-gdb.log --report reports/pico-debug.html \
  --map .pio/build/rpipico-debug/firmware.map --source-root ./target-firmware \
  --coverage reports/coverage-report.json
```

`--halt` hedefi durdurmak için açıkça izin verir; script flash/erase/reset veya
belleğe yazma komutu üretmez. Offline core dosyası için `--remote` yerine
`--core captures/core.dump` kullan. Tüm detaylar: `docs/DEBUGGER_INTEGRATION.md`.

## 13) Checksum-aware crash minimization

Sabit konumlu checksum kullanan protokoller için JSON checksum tanımı ver:

```bash
python3 tools/nexus_minimize.py \
  --input crashes/original.bin --output crashes/minimized.bin \
  --oracle-command 'python3 replay_fixture.py --input {input}' \
  --checksum-spec examples/protocols/demo-crc16.json \
  --immutable-prefix 1 --repetitions 3 --required-reproductions 2 \
  --report crashes/minimized.json
```

Her aday için checksum tekrar hesaplanır. Sabit offset'ler korunabilsin diye
checksum spec kullanıldığında frame uzunluğu değiştirilmez. JSON içindeki
algoritma, veri aralığı, checksum offset'i ve byte order hedef protokolle aynı
olmalıdır.

## 14) Tam native test matrisi

```bash
./scripts/test_matrix.sh
```

Release + warnings-as-errors derlemesi, tüm CTest testleri ve ayrı
AddressSanitizer/UndefinedBehaviorSanitizer derlemesi çalıştırılır. Donanım
firmware derlemesi ayrıca PlatformIO ve ilgili mimari toolchain'i gerektirir.

## 15) Tek komut arayüzü ve debugger workbench örneği

`tools/nexus.py` araçları tek giriş noktasından çağırır:

```bash
python3 tools/nexus.py version
python3 tools/nexus.py sim --host-optimize 4096 optimized_corpus.hpp
python3 tools/nexus.py triage --input captures/combined.log --elf build/firmware.elf --format html --output reports/crash.html
python3 tools/nexus.py debug --profile rp2040 --elf build/firmware.elf --remote localhost:3333 --dry-run
python3 tools/nexus.py minimize --help
python3 tools/nexus.py test
```

`examples/reports/debugger-workbench-demo.html` dosyası tersine mühendislik/debugger tarzındaki HTML raporu gösterir. Örneği `examples/debugger_fixture/build_demo.sh` ile tekrar üretebilirsin. Bu örnekteki GDB kaydı sentetiktir; fiziksel bir hedefe bağlanmaz ve gerçek cihaz çökmesi iddiası taşımaz.

## v0.7.0 — feedback-guided campaign ve hedef coverage sideband

v0.7.0, v0.6.0'ın debugger/forensic workbench katmanının üzerine campaign scheduler ve target-feedback korelasyonunu ekler.

### Campaign engine

- Fixed-memory `CoverageGuidedScheduler`: en fazla 16 seed, deterministik xorshift weighted selection, sabit outcome tablosu ve sınırlı çalışma maliyeti.
- Feedback map 3072 bit olarak ayrılmıştır: target instrumentation `0–2047`, protokol durum geçişleri `2048–3071` aralığındadır. Bu iki ölçüm birbirine karıştırılmaz.
- Seed admission yeni coverage, komut/yanıt sınıfı yeniliği veya güvenilir bir dış crash oracle'ının doğruladığı crash girdisi ile yapılır. Timeout tek başına confirmed crash sayılmaz.
- State fingerprint hash'i kimlik anahtarı olarak kullanılmaz; state graph ve corpus dedup tam yanıt baytlarını da karşılaştırır.

Host kampanya örneği:

```bash
./scripts/build_native.sh
python3 tools/nexus.py campaign 2500 1337 examples/reports/host-campaign-demo.jsonl
python3 tools/nexus.py dashboard --input examples/reports/host-campaign-demo.jsonl \
  --output examples/reports/host-campaign-dashboard.html
```

Bu rapor yalnızca deterministik, kurgusal host fixture'ını gösterir; fiziksel hedefin binary coverage'ı değildir.

### ESP32-S3 target coverage sideband

`NEXUS_TARGET_DIAG_UART_ENABLED=1` ile ESP32-S3 üzerinde fuzz bus'ından ayrı hedef diagnostic UART etkinleştirilir. Yalnızca log tap'i için `NEXUS_TARGET_COV_SYNC_ENABLED=0` bırak; gerçek per-case coverage için iki bayrağı da `1` yap. NEXUS her vaka öncesi `NXCOV_BEGIN,<case_id>` komutunu gönderir. Hedef firmware `include/nexus/target_coverage_link.hpp` içindeki `TargetCoverageSession` ile komutu alır; bitmap'i vaka başında temizler ve parser/state-machine işlendikten sonra `NXCOV1,run=<case_id>,bits=2048,bitmap=<512 hex chars>` kaydını geri yollar.

Hedefte entegrasyon deseni `examples/instrumented_target/coverage_example.cpp` içindedir:

```cpp
nexus_poll_coverage_control();       // target main loop içinde sık çağır
// hedef bus isteğini parse/dispatch et
nexus_emit_coverage_after_request();  // parser/state machine tamamlanınca çağır
```

Bu entegrasyon hedef firmware değişikliği ve iki yönlü ayrı UART gerektirir. Sadece receive-only panic konsolu, case ID korelasyonu veya gerçek per-case coverage sağlamaz. Pinler ve gerilim seviyeleri kart şemasıyla doğrulanmalıdır. Firmware tarafında kayıt kaybolursa NEXUS protokol-transition feedback'e döner ve `target_cov=0` raporlar.

RP2040/Pico v0.7.0 runner aynı scheduler ile gözlemlenebilir protokol geçişlerini ve response novelty'yi kullanır. Bu sürüm RP2040'da target binary coverage sideband'ini etkinleştirmez; `target_binary_coverage=not_instrumented` olarak açıkça raporlar.

### Protocol manifest compiler

```bash
python3 tools/nexus_protocol.py \
  --input examples/protocols/lab-demo-v1.json \
  --output generated/lab_protocol.hpp
```

Manifest şeması, yalnızca `documented_read_only` olarak sınıflandırılan, operatörce incelenmiş frame tanımlarını C++ `SeedSet` ve `ProtocolProfile` koduna dönüştürür. Ayrıntı: `docs/PROTOCOL_MANIFESTS.md`.

### Campaign dashboard

JSONL kayıtları offline HTML dashboard'a çevrilir. Case ID, parent seed, mutation, input/response, response class, latency, feedback edges, novelty ve corpus admission bilgileri incelenebilir. Ayrıntı: `docs/CAMPAIGN_ENGINE.md`.

## v0.5.0 doğrulama özeti

- GCC 14.2 ile C++20 Release + warnings-as-errors: PASS.
- Release CTest: 11/11; ayrı ASan/UBSan Debug CTest: 11/11 PASS.
- GDB/OpenOCD yakalama yardımcısı; mimariye göre GDB profili, canlı/offline betik, Build ID çıkarımı ve sahte GDB transcript testi: PASS.
- Triage parser; GDB register/frame, SIGSEGV/SIGTRAP ayrımı, target Build ID ile analiz ELF Build ID ayrımı: PASS.
- CRC standart test vektörleri, checksum-aware minimization/quorum, host corpus ve yerel 256-opcode simülatörü: PASS.
- ESP32-S3 ve RP2040 fiziksel firmware derlemesi/yüklemesi ile JTAG/SWD bağlantısı bu ortamda doğrulanmadı.


## v0.6.0 — mühendislik sağlamlaştırması ve adli inceleme akışı

Bu sürüm, v0.5.0 debugger/forensic altyapısının üzerine aşağıdaki iyileştirmeleri ekler:

- Engine konfigürasyonu, transport açılmadan önce doğrulanır. Geçersiz timeout,
  aşırı test bütçesi, hatalı sigma eşiği ve eksik heartbeat imzası reddedilir.
- Corpus'un tamamı ilk kalibrasyon paketi gönderilmeden doğrulanır. Sonraki bir
  seed geçersizse hedef kısmen test edilmiş halde bırakılmaz.
- State Graph, 32-bit fingerprint'e ek olarak tam yanıt baytlarını karşılaştırır;
  hash çakışması iki protokol durumunu yanlışlıkla birleştiremez.
- UART/transport yanıtı 128 byte sınırını aşarsa `OversizedResponse` olarak
  sınıflandırılır; kesilmiş cevap geçerli protokol yanıtı gibi yorumlanmaz.
- RP2040 monotonic saati artık `time_us_64()` kullanır; 32-bit `micros()`
  sayacının yaklaşık 71 dakikada sarılması uzun kampanyaları bozmaz.
- `nexus doctor`: host, PlatformIO, OpenOCD ve mimariye özel debug toolchain
  ön kontrolü.
- `nexus session`: birleşik UART/panic/GDB logunu JSONL olay akışına dönüştürür.
- `nexus bundle`: capture, ELF, MAP, coverage ve minimized trigger'ı SHA-256
  manifestiyle tek bir offline inceleme ZIP dosyasında toplar.
- Canlı GDB yakalama için açık `--halt` onayı zorunlu hale getirildi. `--dry-run`
  donanıma bağlanmadan komut dosyasını üretir.
- Coverage edge ID daraltma taşması ve bitmap kapasitesi kontrolleri güçlendirildi;
  custom CRC parametrelerinin seçili CRC genişliğine sığması zorunlu kılındı.

### Önerilen uçtan uca kullanım

Önce ortamı kontrol et:

```bash
python3 tools/nexus.py doctor
```

Host simülasyonu ve corpus optimizasyonu:

```bash
./scripts/build_native.sh
./build/nexus_sim --host-optimize 4096 optimized_corpus.hpp
```

Birleşik logu JSONL'e dönüştür:

```bash
python3 tools/nexus.py session \
  --input captures/combined.log \
  --output reports/session.jsonl \
  --summary reports/session-summary.json
```

Ayrıntılı debugger raporu:

```bash
python3 tools/nexus.py triage \
  --input captures/combined.log \
  --elf .pio/build/esp32s3-debug/firmware.elf \
  --map .pio/build/esp32s3-debug/firmware.map \
  --coverage reports/coverage-report.json \
  --source-root ./target-firmware \
  --format html --output reports/crash.html
```

Adli kanıt paketini üret:

```bash
python3 tools/nexus.py bundle \
  --capture captures/combined.log \
  --elf .pio/build/esp32s3-debug/firmware.elf \
  --map .pio/build/esp32s3-debug/firmware.map \
  --coverage reports/coverage-report.json \
  --minimized-input crashes/minimized.bin \
  --source-root ./target-firmware \
  --output reports/case-evidence.zip
```

Bundle yalnızca açıkça verdiğin dosyaları kopyalar; kaynak deposunun tamamını
paketlemez. JSON/HTML analiz raporlarını ve dosyaların SHA-256 özetlerini içerir.
Paylaşmadan önce ELF ve logların gizli bilgilerini kontrol et.

## v0.6.0 doğrulama kapsamı

Native Release + warnings-as-errors ve ayrı ASan/UBSan testleri host tarafında
çalıştırılır. ESP32-S3 / RP2040 cross-build, JTAG/SWD ve fiziksel UART/SPI/I²C
kontrolleri yalnızca PlatformIO, uygun toolchain ve gerçek donanım kurulduğunda
ayrıca doğrulanabilir; bu paket bunların fiziksel test edildiği iddiasında değildir.


## v0.7.0 test durumu

Bu kaynak paketin native C++20 Release + warnings-as-errors derlemesi ve ayrı
ASan/UBSan derlemesi 17/17 CTest ile doğrulanmıştır. Hedef sideband parser'ı
`NXCOV_BEGIN` / `NXCOV_READY` / `NXCOV1` senaryolarıyla mock stream üzerinde
test edilmiştir. ESP32-S3 / RP2040 PlatformIO firmware derlemesi ve fiziksel
kart bağlantısı bu ortamda yapılmamıştır; gerçek hedefte kullanmadan önce kendi
kart pinlerini, seviye uyumunu, hedef firmware hook'larını ve panic/coverage
çıktısını laboratuvar düzeneğinde doğrula.
