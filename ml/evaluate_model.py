"""
Skrip evaluasi metrik model penilaian citra (NFR-012 & TC-017).
Menghasilkan Accuracy, Precision, Recall, F1-Score, dan Confusion Matrix.

Jalankan:
    python -m ml.evaluate_model
"""
from collections import Counter
from typing import List, Sequence

LABELS = ["Kurang Layak", "Cukup", "Baik", "Sangat Baik"]


def compute_classification_report(y_true: Sequence[str], y_pred: Sequence[str], labels: List[str] = LABELS) -> dict:
    assert len(y_true) == len(y_pred) and len(y_true) > 0, "Data uji tidak boleh kosong."
    n = len(y_true)
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    accuracy = round(correct / n, 4)

    matrix = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        if t in matrix and p in matrix[t]:
            matrix[t][p] += 1

    per_class = {}
    precisions, recalls, f1s = [], [], []
    for lbl in labels:
        tp = matrix[lbl][lbl]
        fp = sum(matrix[other][lbl] for other in labels if other != lbl)
        fn = sum(matrix[lbl][other] for other in labels if other != lbl)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
        per_class[lbl] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "support": Counter(y_true)[lbl],
        }
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

    return {
        "total_samples": n,
        "accuracy": accuracy,
        "macro_precision": round(sum(precisions) / len(labels), 4),
        "macro_recall": round(sum(recalls) / len(labels), 4),
        "macro_f1": round(sum(f1s) / len(labels), 4),
        "per_class": per_class,
        "confusion_matrix": matrix,
    }


def main():
    # Baseline contoh evaluasi data uji terpisah (ganti dengan hasil prediksi dataset COE saat tersedia)
    sample_true = [
        "Sangat Baik", "Sangat Baik", "Sangat Baik", "Baik",
        "Baik", "Baik", "Baik", "Cukup",
        "Cukup", "Cukup", "Cukup", "Kurang Layak",
        "Kurang Layak", "Kurang Layak", "Kurang Layak", "Cukup",
    ]
    sample_pred = [
        "Sangat Baik", "Sangat Baik", "Baik", "Baik",
        "Baik", "Baik", "Cukup", "Cukup",
        "Cukup", "Cukup", "Cukup", "Kurang Layak",
        "Kurang Layak", "Kurang Layak", "Cukup", "Cukup",
    ]
    report = compute_classification_report(sample_true, sample_pred)
    print("=== Laporan Evaluasi Model Citra Local Thrift (NFR-012 / TC-017) ===")
    print(f"Total Sampel Uji : {report['total_samples']}")
    print(f"Accuracy         : {report['accuracy'] * 100:.2f}%")
    print(f"Macro Precision  : {report['macro_precision'] * 100:.2f}%")
    print(f"Macro Recall     : {report['macro_recall'] * 100:.2f}%")
    print(f"Macro F1-Score   : {report['macro_f1'] * 100:.2f}%")
    print("\nConfusion Matrix (Baris=Aktual, Kolom=Prediksi):")
    header = f"{'Aktual \\ Pred':<15} " + " ".join(f"{lbl[:10]:>11}" for lbl in LABELS)
    print(header)
    for t in LABELS:
        row_str = f"{t:<15} " + " ".join(f"{report['confusion_matrix'][t][p]:>11}" for p in LABELS)
        print(row_str)


if __name__ == "__main__":
    main()
