# MOne CoalChain

Aplikasi Mining Contractor Management System berdasarkan **FSD_DOCUMENTS/FSD_Mining_Contractor_Management_System-1.docx**, termasuk technology stack pada bagian 40.

React + TypeScript PWA, Python FastAPI, Node.js background worker, MySQL 8.4, dan Docker Compose. Versi awal ini menyediakan alur operasional sampai payment yang dapat dijalankan dan diuji. Lihat [cakupan FSD](docs/FSD_COVERAGE.md) untuk fitur yang sudah ada dan batas implementasinya.

## Menjalankan lokal di Windows

Prasyarat: Python 3.13 dan Node.js 24. Dari PowerShell pada repository:

```powershell
.\scripts\start-local.ps1 -Demo
```

Buka **http://127.0.0.1:5173**.

- Email: **admin@coalchain.local**
- Password demo lokal: **CoalChain-Local-2026!**

Script memasang dependensi di **%LOCALAPPDATA%/MOne-CoalChain/dev**, sehingga tidak terganggu sinkronisasi Google Drive. Database SQLite dan lampiran lokal juga disimpan di sana. Source tetap di repository. Jalankan ulang script setelah perubahan frontend agar salinan runtime diperbarui. SQLite hanya untuk pengembangan, bukan deployment produksi.

Tanpa `-Demo`, aplikasi membuat admin dan database kosong; password awal diminta saat menjalankan script. Seed operasional demo dijalankan ketika database belum memiliki records. Jika belum ada master stockpile, mode demo juga menambahkan Stockpile Main dengan saldo awal 12.500 ton. Mengganti environment password tidak mereset akun yang sudah ada; gunakan menu profil untuk mengganti password.

Akun role tambahan tersedia hanya pada demo, misalnya `contractor.user@coalchain.local`, `contractor.supervisor@coalchain.local`, `owner.supervisor@coalchain.local`, `surveyor@coalchain.local`, `commercial@coalchain.local`, `finance@coalchain.local`, dengan password demo yang sama. Akun kontraktor demo dibatasi ke kontraktor pertama.

## Menjalankan stack MySQL dengan Docker

Aktifkan Docker Desktop dengan Linux containers. Salin konfigurasi:

```powershell
Copy-Item .env.example .env
```

Ganti seluruh nilai password/secret di `.env`. Password admin minimum 12 karakter. Lalu:

```powershell
docker compose up --build -d
```

Buka **http://localhost:8080**. Login sebagai `admin@coalchain.local` menggunakan `MCMS_ADMIN_PASSWORD` di `.env`.

Untuk data simulasi, gunakan opt-in ini sejak database masih kosong:

```powershell
docker compose -f compose.yaml -f compose.demo.yaml up --build -d
```

Pemeriksaan dan penghentian:

```powershell
docker compose ps
docker compose logs api worker
docker compose down
```

`docker compose down` mempertahankan volume database dan dokumen. Jangan menggunakan `down -v` pada data yang perlu dipertahankan.

Port web hanya di-bind ke loopback. Sebelum akses jaringan/produksi, pasang reverse proxy HTTPS, set `MCMS_SECURE_COOKIE=true`, ganti kredensial, serta siapkan backup dan monitoring. Worker dan database tidak membuka port host.

## Alur penggunaan

1. Buat site, pit, kontraktor, equipment, dan lokasi.
2. Buat kontrak serta rate; submit dan selesaikan approval. Tambahkan monthly mining plan.
3. Buat master **Stockpile & saldo** untuk setiap ROM, intermediate stockpile, port, atau jetty. Tentukan kapasitas, minimum stock, saldo awal, dan coal specification.
4. Catat **Coal hauling** dari lokasi asal ke stockpile tujuan melalui moda **Darat**, **Sungai**, atau **Laut**. Masukkan jarak satu arah, rit/voyage, tonase, dan DO/surat jalan/BOL. Setelah Owner Supervisor menyetujui, sistem membuat penerimaan stockpile otomatis.
5. Catat **Mutasi stockpile** untuk addition, shipment/sale, transfer out, quality adjustment, shrinkage, atau stock count. Mutasi OUT ditolak jika melebihi saldo buku dan mutasi manual membutuhkan approval Owner Supervisor.
6. Input daily production. Tambahkan lampiran sebelum submit. Contractor Supervisor lalu Owner Supervisor melakukan approval hingga **VERIFIED**.
7. Buat survey sesuai pit, block, activity, material, unit, dan periode produksi. Quantity harus sama dengan selisih volume. Selesaikan approval Surveyor, Engineering, lalu Owner.
8. Buat rekonsiliasi dari DPR verified dan survey approved, lalu progress claim. Rate, quantity, jarak, retensi, penalty, incentive, dan net dihitung server. Selesaikan approval claim, invoice, dan catat payment reference hingga invoice **CLOSED**.

Admin dapat menjalankan semua tahap untuk pengujian. Pada operasional, gunakan akun role masing-masing.

## Modul

- Control tower: produksi verified vs monthly plan, fleet, scorecard, alert, contract utilization.
- Master data: site, pit/block/seam, lokasi/rute, kontraktor.
- Operations: equipment, manpower, mining plan, DPR, **Coal hauling multi-moda**, master **Stockpile & saldo**, serta **Mutasi stockpile**.
- Assurance: survey dan rekonsiliasi.
- Performance: fuel, HSE, scorecard.
- Commercial: kontrak, rate, amendment, rule penalty/incentive, claim, invoice/payment, cost analytics.
- Administrasi: approval inbox, audit, user/scope, threshold, bobot KPI, workflow, nama aplikasi, dan upload logo.
- Dokumen ber-versi, CSV export, CSV/XLSX import dengan preview dan konfirmasi atomik.

## Offline PWA

Production build menyediakan manifest dan service worker untuk app shell. Pada aplikasi yang sudah dibuka/login, DPR, fuel, dan HSE baru dapat disimpan sebagai draft ketika koneksi putus. Buka **Draft offline** setelah terhubung, lalu kirim satu per satu ke server. Data kembali divalidasi server dan tetap berupa draft, bukan langsung approved.

Draft tersimpan per akun di browser pada perangkat tersebut. Jangan menghapus storage browser sebelum menyinkronkan. API/attachment tidak di-cache service worker; login dan reload data transaksi tetap membutuhkan koneksi. Fitur offline tidak menjanjikan database operasional lengkap atau background sync otomatis.

## Pengembangan manual

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
$env:DATABASE_URL = 'sqlite:///./dev.db'
$env:MCMS_ADMIN_PASSWORD = 'replace-with-a-strong-password'
$env:PYTHONPATH = 'backend'
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal kedua:

```powershell
npm ci
npm run dev
```

Folder sinkronisasi seperti Google Drive dapat gagal saat menulis ribuan dependency files; gunakan launcher lokal di atas bila terjadi.

## API dan pengujian

- OpenAPI: **http://127.0.0.1:8000/api/docs**
- Health: `GET /api/health`
- Auth: `POST /api/auth/login`, `GET /api/auth/me`
- Stockpile overview: `GET /api/stockpiles/overview` (saldo buku, kapasitas, utilisasi, dan minimum stock)
- CRUD: `/api/records/{module}`, `/api/record/{id}`
- Approval: `POST /api/record/{id}/action`
- Import: `/api/import/{module}/preview`, `/api/import/confirm/{batch_id}`
- Set header `X-MCMS-Request: 1` pada mutasi. Autentikasi memakai HttpOnly session cookie dengan idle timeout 30 menit.

```powershell
$env:PYTHONPATH = 'backend'
python -m pytest backend/tests -q
npm test
npm run build
```

Uji browser opsional, dengan API/frontend demo lokal aktif dan Chrome terpasang:

```powershell
npm install --no-save --package-lock=false "playwright@^1.55.1"
node tests/ui-smoke.mjs
```

Uji UI membuat transaksi HSE simulasi dan screenshot di `qa/`; jalankan hanya pada database demo/test.

Baca [arsitektur](docs/ARCHITECTURE.md), [cakupan FSD](docs/FSD_COVERAGE.md), dan [hasil validasi](docs/VALIDATION.md) sebelum menjadikan versi awal ini dasar rollout operasional.

