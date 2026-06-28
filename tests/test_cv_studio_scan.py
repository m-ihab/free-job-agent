from __future__ import annotations

from job_agent.cv_studio_scan import six_second_scan


VALID_CV = r"""
\documentclass[10pt,a4paper]{moderncv}
\begin{document}
\section{Skills}
Python, SQL, Machine Learning
\section{Projects}
Deep Learning Project -- trained CNN models.
\section{Experience}
Built data workflows.
\section{Education}
MSc Data Science
linkedin.com/in/example github.com/example
\end{document}
"""


def test_six_second_scan_rejects_non_latex_assets():
    result = six_second_scan('{"contact": {"name": "Nope"}}')

    assert result["ok"] is False
    assert result["score"] == 0


def test_six_second_scan_flags_placeholders_without_failing_valid_cv():
    result = six_second_scan(VALID_CV + "\n[X employees]\n")

    assert result["ok"] is True
    assert result["placeholder_count"] == 1
    assert any(issue["severity"] == "high" for issue in result["issues"])
