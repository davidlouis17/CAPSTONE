# Panduan Kontribusi Tim — Local Thrift

Dokumen ini menjadi acuan kerja sama tim agar riwayat kode tetap rapi, mudah di-review, dan minim konflik.

## 1. Strategi Branching

| Branch | Fungsi | Aturan |
| :--- | :--- | :--- |
| `main` | Kode stabil siap demo / produksi | Terproteksi; hanya menerima merge dari `dev` lewat Pull Request |
| `dev` | Integrasi fitur terbaru tim | Target utama untuk Pull Request harian |
| `feat/<nama>` | Pengembangan fitur baru | Dibuat dari `dev` (contoh: `feat/katalog-publik`) |
| `fix/<nama>` | Perbaikan bug | Dibuat dari `dev` (contoh: `fix/grading-grade-d`) |
| `docs/<nama>` | Pembaruan dokumentasi | Dibuat dari `dev` (contoh: `docs/setup-readme`) |
| `refactor/<nama>` | Perapihan struktur kode | Dibuat dari `dev` |

## 2. Alur Kerja Harian

1. Pastikan branch `dev` lokal selalu terbaru:
   ```bash
   git checkout dev
   git pull origin dev
   ```
2. Buat branch baru sesuai tugas:
   ```bash
   git checkout -b feat/nama-fitur
   ```
3. Lakukan perubahan dan commit secara bertahap dengan pesan yang jelas.
4. Push branch ke GitHub dan buka **Pull Request** dengan target branch `dev`:
   ```bash
   git push -u origin feat/nama-fitur
   ```
5. Minta minimal 1 rekan tim melakukan review sebelum melakukan merge.

## 3. Format Pesan Commit (Conventional Commits)

Gunakan awalan standar berikut agar riwayat commit mudah dibaca:

- `feat:` — menambah fitur baru (contoh: `feat: tambah halaman katalog sepatu publik`)
- `fix:` — memperbaiki bug (contoh: `fix: sembunyikan sepatu grade D dari katalog`)
- `docs:` — perubahan dokumentasi (contoh: `docs: lengkapi panduan instalasi di README`)
- `style:` — penyesuaian tampilan/formatting tanpa ubah logika
- `refactor:` — perapihan kode tanpa ubah perilaku fitur
- `test:` — menambah atau memperbarui pengujian
- `chore:` — konfigurasi, dependensi, atau pemeliharaan repo

## 4. Checklist Sebelum Push

- Aplikasi berjalan normal di lokal tanpa error.
- File sensitif atau lokal (`.env`, `*.db`, `.venv/`) tidak ikut masuk staging.
- Tidak ada kode *debugging* yang tertinggal (misalnya `print()` berlebihan).
