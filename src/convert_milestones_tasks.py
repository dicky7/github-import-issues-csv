#!/usr/bin/env python3
#
# SPDX-License-Identifier: MIT
#

"""
Convert separate milestone/task CSV files into the issues CSV format expected by
this repository importer.
"""

import argparse
import csv
import re
from pathlib import Path


OUTPUT_HEADERS = [
    "project_issue_id",
    "project_parent_issue_id",
    "project_estimate",
    "account_type",
    "account_name",
    "repo_name",
    "project_id",
    "project_number",
    "status",
    "milestone",
    "labels",
    "title",
    "body",
]


SIZE_ESTIMATE_DAYS = {
    "XS": 1,
    "S": 2,
    "M": 3,
    "L": 5,
    "XL": 8,
}


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "item"


def ensure_unique(base: str, used: set[str]) -> str:
    candidate = base
    count = 2
    while candidate in used:
        candidate = f"{base}-{count}"
        count += 1
    used.add(candidate)
    return candidate


def clean_label(value: str) -> str:
    return slugify(value or "")


def build_milestone_body(description: str, due_text: str) -> str:
    due_line = f"Due: {due_text.strip()}" if due_text.strip() else "Due: Not specified"
    return f"{description.strip()}\n\n{due_line}"


def build_task_body(description: str, priority: str, size: str, role: str, milestone: str) -> str:
    meta_lines = [
        f"- Priority: {priority or 'N/A'}",
        f"- Size: {size or 'N/A'}",
        f"- Role: {role or 'N/A'}",
        f"- Milestone: {milestone or 'N/A'}",
    ]
    return f"{description.strip()}\n\nMetadata:\n" + "\n".join(meta_lines)


def convert(
    milestones_file: Path,
    tasks_file: Path,
    output_file: Path,
    account_type: str,
    account_name: str,
    repo_name: str,
    project_number: int,
    project_id: str,
    default_status: str,
    no_milestone_issues: bool,
) -> tuple[int, int]:
    used_issue_ids: set[str] = set()
    milestone_issue_id_by_title: dict[str, str] = {}
    output_rows: list[dict[str, str | int]] = []

    with milestones_file.open(newline="", encoding="utf-8-sig") as f:
        milestone_rows = list(csv.DictReader(f))

    with tasks_file.open(newline="", encoding="utf-8-sig") as f:
        task_rows = list(csv.DictReader(f))

    if not no_milestone_issues:
        for row in milestone_rows:
            title = (row.get("Title") or "").strip()
            description = (row.get("Description") or "").strip()
            due_text = (row.get("Due (Week)") or "").strip()
            milestone_issue_id = ensure_unique(f"milestone-{slugify(title)}", used_issue_ids)
            milestone_issue_id_by_title[title] = milestone_issue_id

            output_rows.append(
                {
                    "project_issue_id": milestone_issue_id,
                    "project_parent_issue_id": "",
                    "project_estimate": 0,
                    "account_type": account_type,
                    "account_name": account_name,
                    "repo_name": repo_name,
                    "project_id": project_id,
                    "project_number": project_number,
                    "status": default_status,
                    "milestone": title,
                    "labels": "milestone",
                    "title": title,
                    "body": build_milestone_body(description=description, due_text=due_text),
                }
            )

    orphan_tasks = 0

    for row in task_rows:
        title = (row.get("Title") or "").strip()
        description = (row.get("Description") or "").strip()
        priority = (row.get("Priority") or "").strip()
        size = (row.get("Size") or "").strip().upper()
        role = (row.get("Role") or "").strip()
        milestone_title = (row.get("Milestone") or "").strip()

        milestone_issue_id = milestone_issue_id_by_title.get(milestone_title, "")
        if not milestone_issue_id and not no_milestone_issues:
            orphan_tasks += 1

        task_base = f"task-{slugify(milestone_title)}-{slugify(title)}"
        task_issue_id = ensure_unique(task_base, used_issue_ids)
        estimate = SIZE_ESTIMATE_DAYS.get(size, 0)

        labels = [
            "task",
            f"priority-{clean_label(priority)}" if priority else "",
            f"size-{clean_label(size)}" if size else "",
            f"role-{clean_label(role)}" if role else "",
        ]
        labels = [label for label in labels if label]

        output_rows.append(
            {
                "project_issue_id": task_issue_id,
                "project_parent_issue_id": "" if no_milestone_issues else milestone_issue_id,
                "project_estimate": estimate,
                "account_type": account_type,
                "account_name": account_name,
                "repo_name": repo_name,
                "project_id": project_id,
                "project_number": project_number,
                "status": default_status,
                "milestone": milestone_title,
                "labels": ",".join(labels),
                "title": title,
                "body": build_task_body(
                    description=description,
                    priority=priority,
                    size=size,
                    role=role,
                    milestone=milestone_title,
                ),
            }
        )

    with output_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_HEADERS)
        writer.writeheader()
        writer.writerows(output_rows)

    return len(output_rows), orphan_tasks


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Convert milestone + task CSV files to the issues format expected by "
            "src/import_issue.py."
        )
    )
    parser.add_argument("--milestones-file", required=True, help="Path to milestones CSV file.")
    parser.add_argument("--tasks-file", required=True, help="Path to tasks CSV file.")
    parser.add_argument("--output-file", required=True, help="Path to output issues CSV.")
    parser.add_argument(
        "--account-type",
        default="organization",
        choices=("organization", "user"),
        help="GitHub account type for all rows.",
    )
    parser.add_argument("--account-name", required=True, help="GitHub account (org/user) name.")
    parser.add_argument("--repo-name", required=True, help="GitHub repository name.")
    parser.add_argument(
        "--project-number",
        default=0,
        type=int,
        help="GitHub Project number. Use 0 to skip project import.",
    )
    parser.add_argument(
        "--project-id",
        default="",
        help="Optional custom project_id field value applied to all rows.",
    )
    parser.add_argument(
        "--default-status",
        default="",
        help="Optional status field value applied to all rows.",
    )
    parser.add_argument(
        "--no-milestone-issues",
        action="store_true",
        help=(
            "Do not create parent milestone issues. Only create task issues and assign "
            "their GitHub milestone."
        ),
    )

    args = parser.parse_args()

    row_count, orphan_tasks = convert(
        milestones_file=Path(args.milestones_file),
        tasks_file=Path(args.tasks_file),
        output_file=Path(args.output_file),
        account_type=args.account_type,
        account_name=args.account_name,
        repo_name=args.repo_name,
        project_number=args.project_number,
        project_id=args.project_id,
        default_status=args.default_status,
        no_milestone_issues=args.no_milestone_issues,
    )

    print(f"Wrote {row_count} rows to {args.output_file}")
    if orphan_tasks:
        print(
            f"Warning: {orphan_tasks} tasks had milestones not found in milestone CSV "
            "and were imported without parent linkage."
        )


if __name__ == "__main__":
    main()
