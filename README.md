# Local Thrift — Second-Hand Shoe Curation System

Sistem web kurasi sepatu *second-hand* **Local Thrift** untuk proyek Capstone **COE Telkom University Surabaya**. Aplikasi ini membantu proses kurasi, verifikasi fisik, penilaian kondisi otomatis berbasis CNN, penetapan harga deterministik, hingga publikasi katalog sepatu layak jual.

## Fitur Utama

- **Katalog Sepatu Publik**: Menampilkan daftar sepatu yang lolos kurasi dengan informasi kondisi dan harga secara transparan.
- **Admin 4-Angle Photo Input & Physical Verification Gate**: Alur unggah foto sepatu dari 4 sudut utama disertai gerbang verifikasi fisik oleh admin sebelum masuk penilaian.
- **Deterministic 4-Criteria Grading & Pricing Rule Engine**: Penentuan grade dan harga secara deterministik berdasarkan 4 kriteria kondisi, dengan penyaringan otomatis agar sepatu **Grade D** tidak ditampilkan di katalog publik.
- **Integrasi Modul CNN Evaluasi Kondisi Sepatu**: Modul *Convolutional Neural Network* berbasis Python untuk membantu evaluasi kondisi visual sepatu.
- **Audit Log**: Pencatatan riwayat verifikasi, perubahan status, dan aktivitas kurasi untuk transparansi operasional.

## Tech Stack

| Komponen | Teknologi |
| :--- | :--- |
| Backend & API | Python, FastAPI |
| Template Engine | Jinja2 HTML Templates |
| Styling | Tailwind CSS |
| Database | SQLite (`local_thrift_system`) |
| Machine Learning | Python CNN (Evaluasi Kondisi Sepatu) |

## Struktur Direktori yang Disarankan

```text
CAPSTONE/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── PULL_REQUEST_TEMPLATE.md
├── app/
│   ├── main.py
│   ├── routers/
│   ├── services/
│   ├── templates/
│   └── static/
├── ml/
│   └── models/
├── tests/
├── .env.example
├── .gitignore
├── CONTRIBUTING.md
├── README.md
└── requirements.txt
```

## Cara Menjalankan di Lokal

1. **Clone repositori dan pindah ke branch `dev`**
   ```bash
   git clone https://github.com/davidlouis17/CAPSTONE.git
   cd CAPSTONE
   git checkout dev
   ```

2. **Buat dan aktifkan virtual environment**
   ```bash
   python3 -m venv .venv
   # Bash / Zsh:
   source .venv/bin/activate
   # Fish shell:
   source .venv/bin/activate.fish
   # Windows (PowerShell):
   .venv\Scripts\Activate.ps1
   ```

3. **Install dependensi**
   ```bash
   pip install -r requirements.txt
   ```

4. **Siapkan file environment**
   ```bash
   cp .env.example .env
   ```
   Sesuaikan nilai konfigurasi di `.env` jika diperlukan.

5. **Jalankan server pengembangan**
   ```bash
   uvicorn app.main:app --reload
   ```
   Aplikasi dapat diakses melalui `http://127.0.0.1:8000`.

## Alur Kolaborasi Git

- **`main`**: Branch rilis stabil (jangan push langsung ke sini).
- **`dev`**: Branch integrasi pengembangan utama tim.
- **`feat/<nama-fitur>` / `fix/<nama-bug>`**: Branch kerja harian per fitur atau perbaikan.

Baca panduan lengkapnya di [CONTRIBUTING.md](CONTRIBUTING.md).

## Tim Pengembang

| Peran | Anggota |
| :--- | :--- |
| Backend & API (FastAPI / SQLite) | _(Isi nama & username GitHub)_ |
| Frontend & UI (Jinja2 / Tailwind CSS) | _(Isi nama & username GitHub)_ |
| Machine Learning (Python CNN) | _(Isi nama & username GitHub)_ |
| QA & Dokumentasi | _(Isi nama & username GitHub)_ |
