from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas


OUT = Path("resume_work/Aditya_Anand_Resume_updated.pdf")

WIDTH, HEIGHT = letter
LEFT = 42
RIGHT = 42
TOP = 32
BOTTOM = 28
BODY_FONT = "Helvetica"
BOLD_FONT = "Helvetica-Bold"


def fit_text(text: str, font: str, size: float, max_width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = word if not line else f"{line} {word}"
        if stringWidth(candidate, font, size) <= max_width:
            line = candidate
        else:
            if line:
                lines.append(line)
            if stringWidth(word, font, size) <= max_width:
                line = word
            else:
                pieces = wrap(word, width=max(8, int(max_width / (size * 0.55))))
                lines.extend(pieces[:-1])
                line = pieces[-1]
    if line:
        lines.append(line)
    return lines


class Resume:
    def __init__(self) -> None:
        OUT.parent.mkdir(exist_ok=True)
        self.c = canvas.Canvas(str(OUT), pagesize=letter)
        self.y = HEIGHT - TOP

    def text(self, x: float, y: float, value: str, font: str = BODY_FONT, size: float = 8.3) -> None:
        self.c.setFont(font, size)
        self.c.drawString(x, y, value)

    def centered(self, y: float, value: str, font: str = BODY_FONT, size: float = 8.3) -> None:
        self.c.setFont(font, size)
        self.c.drawCentredString(WIDTH / 2, y, value)

    def right(self, y: float, value: str, font: str = BODY_FONT, size: float = 8.3) -> None:
        self.c.setFont(font, size)
        self.c.drawRightString(WIDTH - RIGHT, y, value)

    def section(self, title: str) -> None:
        self.y -= 10
        self.text(LEFT, self.y, title.upper(), BOLD_FONT, 9.4)
        self.c.setLineWidth(0.45)
        self.c.line(LEFT, self.y - 2.2, WIDTH - RIGHT, self.y - 2.2)
        self.y -= 10.2

    def role_header(
        self,
        org: str,
        location: str,
        role: str,
        dates: str,
    ) -> None:
        self.text(LEFT, self.y, org.upper(), BOLD_FONT, 8.4)
        self.right(self.y, location, BODY_FONT, 8.2)
        self.y -= 9.2
        self.text(LEFT, self.y, role, BOLD_FONT, 8.25)
        self.right(self.y, dates, BODY_FONT, 8.2)
        self.y -= 8.6

    def project_header(self, name: str, stack: str) -> None:
        self.text(LEFT, self.y, name, BOLD_FONT, 8.35)
        name_w = stringWidth(name, BOLD_FONT, 8.35)
        self.text(LEFT + name_w + 3.5, self.y, f"| {stack}", BODY_FONT, 8.05)
        self.y -= 8.4

    def bullet(self, text: str, size: float = 7.72, leading: float = 8.6) -> None:
        bullet_x = LEFT + 3.5
        text_x = LEFT + 12
        max_width = WIDTH - RIGHT - text_x
        lines = fit_text(text, BODY_FONT, size, max_width)
        self.text(bullet_x, self.y, "-", BODY_FONT, size)
        for i, line in enumerate(lines):
            self.text(text_x, self.y - (i * leading), line, BODY_FONT, size)
        self.y -= leading * len(lines)

    def skill_line(self, label: str, text: str) -> None:
        label_text = f"{label}:"
        self.text(LEFT, self.y, label_text, BOLD_FONT, 7.72)
        x = LEFT + stringWidth(label_text + " ", BOLD_FONT, 7.72)
        max_width = WIDTH - RIGHT - x
        lines = fit_text(text, BODY_FONT, 7.72, max_width)
        for i, line in enumerate(lines):
            self.text(x if i == 0 else LEFT, self.y - (i * 8.5), line, BODY_FONT, 7.72)
        self.y -= 8.5 * len(lines)

    def finish(self) -> None:
        self.c.showPage()
        self.c.save()


def build() -> None:
    r = Resume()

    r.centered(r.y, "ADITYA ANAND", BOLD_FONT, 15.0)
    r.y -= 11.5
    r.centered(
        r.y,
        "adianand2002@gmail.com | +91 8728009774 | linkedin.com/in/adianand912 | github.com/Adiii1436",
        BODY_FONT,
        8.0,
    )

    r.section("Work Experience")
    r.role_header("Infogain Corporation", "Bangalore, India", "Associate Software Engineer", "July 2025 - Present")
    r.bullet(
        "Designed and operated distributed PySpark ETL pipelines on Azure Databricks in a large distributed computing environment, processing gigabytes of enterprise data at scale."
    )
    r.bullet(
        "Built scalable, fault-tolerant, and low-cost automated CDC reconciliation frameworks to validate data integrity across distributed storage systems, embedding test-driven and CI/CD-aligned engineering discipline."
    )
    r.bullet(
        "Collaborated with project managers and technical leads to translate business requirements into compliant, production-ready ingestion pipelines, practicing Agile delivery and iterative stakeholder feedback cycles."
    )

    r.y -= 3.0
    r.role_header(
        "Samsung Research and Development",
        "Bangalore, India (Remote)",
        "Research Intern",
        "Feb 2023 - Sep 2023",
    )
    r.bullet(
        "Designed a multi-node distributed microservices system on Kubernetes, applying computer science fundamentals and algorithm design to cut API response time by 25% and optimize server load by 30%."
    )
    r.bullet(
        "Integrated an Open Log Forwarder into existing multi-tiered systems, handling ambiguous infrastructure problems and improving large-scale production observability."
    )
    r.bullet(
        "Created solutions to run predictions on distributed systems, building real-time Grafana dashboards for peak-hour troubleshooting of inference services at scale."
    )

    r.section("Projects")
    r.project_header("Web to DB Automator", "Python, Streamlit, LangGraph, Gemini, Tavily, Supabase/Postgres")
    r.bullet(
        "Built a LangGraph-powered Streamlit agent that researches web sources with Tavily, extracts evidence-backed structured rows with Gemini, previews table data, and prepares safe Supabase/Postgres upserts."
    )
    r.bullet(
        "Implemented a human-in-the-loop write gate with schema/SQL previews, SELECT-only query protection, audit logging, and unit-tested routing guards to prevent unintended database mutations."
    )

    r.y -= 1.5
    r.project_header("Alloy AI - Code Assistant", "TypeScript, Node.js, VS Code API")
    r.bullet(
        "Architected privacy-first AI coding software using Object-Oriented Design and a Merkle Tree Indexer for scalable, high-precision context retrieval across local repositories."
    )
    r.bullet(
        "Designed and coded a custom token compression algorithm to efficiently handle large error logs across multi-LLM backends such as Gemini and OpenAI before shipping to the VS Code Marketplace."
    )

    r.y -= 1.5
    r.project_header("Context Aware File Organizer", "Python, Llama.cpp, PySide6")
    r.bullet(
        "Built a fully offline GenAI pipeline that clusters documents with local vector embeddings and Agglomerative Clustering, then uses a local Llama inference engine to generate context-aware folder names."
    )
    r.bullet(
        "Chose llama.cpp for quantization support and CPU/GPU portability, gaining hands-on understanding of the LLM inference stack behind production AI services."
    )

    r.section("Skills")
    r.skill_line(
        "Computer Science Fundamentals",
        "Object-Oriented Design (OOD), Data Structures, Algorithm Design, Complexity Analysis, Problem Solving, Optimization Mathematics.",
    )
    r.skill_line("Languages", "Python, C, C++, SQL.")
    r.skill_line(
        "Distributed Systems & Architecture",
        "Distributed Computing Environments, Multi-Tiered Systems, Distributed Storage & Query Systems, Microservices, Kubernetes, Docker, Apache Spark (PySpark).",
    )
    r.skill_line(
        "Development & Practices",
        "Agile Environment, Relational Databases, CI/CD, Git, Linux, System Observability (Grafana, Elasticsearch).",
    )
    r.skill_line(
        "AI / GenAI",
        "LangGraph, LangChain, ChromaDB, RAG, Transformer Architectures, LLM Inference Optimization, Gemini, OpenAI.",
    )

    r.section("Education")
    r.role_header("Chandigarh University", "Chandigarh, India", "Bachelor of Engineering", "Jun 2021 - Jun 2025")
    r.text(LEFT, r.y, "Major in Computer Science with Specialization in AIML", BODY_FONT, 7.72)
    r.right(r.y, "CGPA: 7.8/10", BODY_FONT, 7.72)
    r.y -= 8.5
    r.bullet(
        "Relevant Coursework: Artificial Intelligence; Machine Learning; Distributed Systems; Data Structure & Algorithms; Computer Networks.",
        size=7.72,
        leading=8.5,
    )

    r.finish()


if __name__ == "__main__":
    build()
    print(OUT)
