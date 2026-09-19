"""Generate the two deliberately messy demo source files.

Run:  python seed_demo.py

Every defect in this data is intentional and is listed at the bottom of this
file, so the reviewer can check the agent against ground truth.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

LEGACY_COLUMNS = [
    "Emp ID",
    "Employee Name",
    "Email Address",
    "Contact No",
    "DOB",
    "DOJ",
    "Dept",
    "Job Title",
    "Employee Status",
    "Remarks",
]

# Emp ID, Name, Email, Contact, DOB, DOJ, Dept, Job Title, Status, Remarks
LEGACY_ROWS = [
    ["EMP1001", "  Rajesh  Kumar ", "RAJESH.KUMAR@ACME-CORP.COM ", "+91 98765 43210",
     "12/08/1988", "01/04/2015", "Engineering", "Senior Engineer", "Active", "migrated from AS400"],
    ["EMP1002", "priya sharma", "priya.sharma@acme-corp.com", "9876543211",
     "23/07/1991", "15/06/2017", " engineering ", "Engineering Manager", "ACTIVE", ""],
    ["EMP1003", "Amit Verma", "amit.verma@acme-corp.com", "+919876543212",
     "05/11/1985", "10/01/2013", "Finance", "Finance Controller", "Active", ""],
    # exact duplicate row within the same file
    ["EMP1003", "Amit Verma", "amit.verma@acme-corp.com", "+919876543212",
     "05/11/1985", "10/01/2013", "Finance", "Finance Controller", "Active", ""],
    # invalid calendar date (31 February)
    ["EMP1004", "SUNITA  RAO", "sunita.rao@acme-corp.com", "98765 43213",
     "31/02/1990", "22/09/2019", "Human Resources", "HR Business Partner", "active", "check DOB"],
    ["EMP1005", "Vikram Singh", "vikram.singh@acme-corp.com", "+91-9876543214",
     "17/03/1992", "05/05/2020", "Sales", "Regional Sales Lead", "Active", ""],
    ["EMP1006", "Neha  Gupta", "NEHA.GUPTA@acme-corp.com", "9876543215",
     "09/12/1993", "11/11/2021", "Marketing", "Brand Manager", "Inactive", ""],
    ["EMP1007", "Arjun Mehta", "arjun.mehta@acme-corp.com", "+91 9876543216",
     "28/06/1987", "03/03/2016", "Engineering", "Principal Engineer", "Active", ""],
    ["EMP1008", "Kavya  Nair", "kavya.nair@acme-corp.com ", "9876543217",
     "14/01/1995", "19/07/2022", "Design", "Product Designer", "ACTIVE", ""],
    # transient target failure - recovers on attempt 3 of the first push
    ["EMP1009", "Rohit Khanna", "rohit.khanna@acme-corp.com", "9876543218",
     "02/02/1989", "08/08/2018", "Engineering", "Staff Engineer", "Active", ""],
    ["EMP1010", "Meera  Iyer", "meera.iyer@acme-corp.com", "+91 98765 43219",
     "21/05/1990", "27/02/2019", "Finance", "Financial Analyst", "Active", ""],
    # department is not in the target platform master data -> permanent rejection
    ["EMP1011", "Sanjay Patil", "sanjay.patil@acme-corp.com", "9876543220",
     "30/09/1984", "14/04/2012", "Ops Excellence", "Operations Head", "Active", ""],
    ["EMP1012", "Divya  Menon", "divya.menon@acme-corp.com", "9876543221",
     "11/11/1994", "01/09/2021", "Human Resources", "Talent Acquisition Specialist",
     "active", ""],
    ["EMP1013", "Farhan  Ali", "farhan.ali@acme-corp.com", "9876543222",
     "03/07/1990", "21/08/2017", "Engineering", "DevOps Engineer", "Active", ""],
    ["EMP1014", "Shreya  Joshi", " SHREYA.JOSHI@ACME-CORP.COM", "9876543223",
     "16/02/1992", "09/10/2019", "Design", "UX Researcher", "Inactive", ""],
    # status conflicts with the HR file ("resigned") -> DUPLICATE_CONFLICT escalation
    ["EMP1017", "Rahul Bose", "rahul.bose@acme-corp.com", "9876543226",
     "08/04/1986", "12/12/2014", "Sales", "Key Account Manager", "Active", ""],
    # email missing here but present in the HR file -> auto-repaired by the merge
    ["EMP1031", "Ananya  Desai", "", "9876543230",
     "19/08/1996", "06/06/2023", "Marketing", "Content Strategist", "Active", "email pending"],
    # email missing in BOTH files -> MISSING_MANDATORY_FIELD escalation
    ["EMP1042", "Karan  Malhotra", "", "9876543241",
     "25/10/1991", "17/01/2020", "Engineering", "QA Engineer", "Active", "contractor conversion"],
]

HR_COLUMNS = [
    "employee_code",
    "fullName",
    "email",
    "mobile",
    "birth_date",
    "joiningDate",
    "department_name",
    "designation",
    "status",
    "location",
]

HR_ROWS = [
    ["EMP1001", "Rajesh Kumar", "rajesh.kumar@acme-corp.com", "9876543210",
     "1988-08-12", "2015-04-01", "Engineering", "Senior Engineer", "active", "Bengaluru"],
    ["EMP1002", "Priya Sharma", "priya.sharma@acme-corp.com", "9876543211",
     "1991-07-23", "2017-06-15", "Engineering", "Engineering Manager", "active", "Bengaluru"],
    ["EMP1017", "Rahul Bose", "rahul.bose@acme-corp.com", "9876543226",
     "1986-04-08", "2014-12-12", "Sales", "Key Account Manager", "resigned", "Mumbai"],
    ["EMP1031", "Ananya Desai", "ananya.desai@acme-corp.com", "9876543230",
     "1996-08-19", "2023-06-06", "Marketing", "Content Strategist", "active", "Pune"],
    ["EMP1015", "Tanvi Kulkarni", "tanvi.kulkarni@acme-corp.com", "9876543224",
     "1993-03-27", "12-Aug-2019", "Customer Success", "CS Manager", "active", "Pune"],
    ["EMP1016", "Nikhil Reddy", "nikhil.reddy@acme-corp.com", "9876543225",
     "1988-11-05", "03-Feb-2016", "Engineering", "Backend Engineer", "Active", "Hyderabad"],
    ["EMP1018", "Pooja Bhatt", "POOJA.BHATT@acme-corp.com ", "9876543227",
     "1994-06-30", "2021-02-01", "Human Resources", "HR Ops Analyst", "ACTIVE ", "Delhi"],
    ["EMP1019", "Sameer Chauhan", "sameer.chauhan@acme-corp.com", "9876543228",
     "1990-01-19", "2018-05-21", "Finance", "Accounts Payable Lead", "left", "Mumbai"],
    ["EMP1020", "Ritika Saxena", "ritika.saxena@acme-corp.com", "9876543229",
     "1995-09-09", "2022-11-14", "Marketing", "Performance Marketing Lead", "active", "Delhi"],
    ["EMP1021", "Gaurav Thakur", "gaurav.thakur@acme-corp.com", "9876543231",
     "1987-12-02", "2015-08-24", "Sales", "Enterprise AE", "active", "Bengaluru"],
    # transient target failure - only recovers on an explicit "Retry failed"
    ["EMP1022", "Ishita Banerjee", "ishita.banerjee@acme-corp.com", "9876543232",
     "1992-04-15", "2020-01-06", "Design", "Design Lead", "active", "Bengaluru"],
    ["EMP1023", "Manish Gupta", "manish.gupta@acme-corp.com", "9876543233",
     "1986-07-11", "2013-09-30", "Engineering", "Engineering Director", "active", "Bengaluru"],
    # exact duplicate row within the same file
    ["EMP1023", "Manish Gupta", "manish.gupta@acme-corp.com", "9876543233",
     "1986-07-11", "2013-09-30", "Engineering", "Engineering Director", "active", "Bengaluru"],
    # designation differs from the legacy file (non-critical -> auto-resolved)
    ["EMP1006", "Neha Gupta", "neha.gupta@acme-corp.com", "9876543215",
     "1993-12-09", "2021-11-11", "Marketing", "Senior Brand Manager", "inactive", "Delhi"],
    # status encoded as "y" -> deterministic enum normalisation
    ["EMP1024", "Aditya Nambiar", "aditya.nambiar@acme-corp.com", "9876543234",
     "1991-02-28", "2019-03-18", "Customer Success", "CS Ops Specialist", "y", "Kochi"],
]


def write_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(LEGACY_COLUMNS)
        writer.writerows(LEGACY_ROWS)


def write_xlsx(path: Path) -> None:
    try:
        from openpyxl import Workbook
    except ImportError:  # pragma: no cover
        print("openpyxl is required: pip install -r requirements.txt", file=sys.stderr)
        raise

    wb = Workbook()
    ws = wb.active
    ws.title = "employees"
    ws.append(HR_COLUMNS)
    for row in HR_ROWS:
        ws.append(row)
    # Keep every cell text so the agent has to do the type inference itself.
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.number_format = "@"
    wb.save(path)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = DATA_DIR / "employees_legacy.csv"
    xlsx_path = DATA_DIR / "employees_hr.xlsx"
    write_csv(csv_path)
    write_xlsx(xlsx_path)

    print(f"Wrote {csv_path}  ({len(LEGACY_ROWS)} rows, {len(LEGACY_COLUMNS)} columns)")
    print(f"Wrote {xlsx_path} ({len(HR_ROWS)} rows, {len(HR_COLUMNS)} columns)")
    print()
    print("Intentional defects (ground truth for the demo):")
    for line in GROUND_TRUTH:
        print(f"  - {line}")


GROUND_TRUTH = [
    "different column names across the two files (Emp ID vs employee_code, ...)",
    "different date formats (DD/MM/YYYY, YYYY-MM-DD, DD-Mon-YYYY)",
    "leading/trailing whitespace and inconsistent casing throughout",
    "1 exact duplicate row inside each file (EMP1003, EMP1023)",
    "5 employees present in BOTH files (EMP1001, EMP1002, EMP1006, EMP1017, EMP1031)",
    "EMP1004 has an impossible date of birth (31/02/1990) -> dropped, optional field",
    "EMP1031 has no email in the legacy file -> auto-filled from the HR file",
    "EMP1042 has no email in ANY file -> ESCALATION (missing mandatory field)",
    "'Contact No' is ambiguous: mobile_phone vs work_phone -> ESCALATION",
    "EMP1017 is Active in legacy and resigned in HR -> ESCALATION (duplicate conflict)",
    "EMP1006 designation differs -> auto-resolved by source precedence (non-critical)",
    "EMP1024 status is 'y' -> deterministic enum normalisation to 'active'",
    "EMP1011 department 'Ops Excellence' is not in target master data -> permanent push failure",
    "EMP1009 hits 2 transient target errors -> auto-retried, succeeds on attempt 3",
    "EMP1022 hits 3 transient target errors -> recovered by the 'Retry failed' button",
    "'Remarks' and 'location' have no target field -> left unmapped, not guessed",
]


if __name__ == "__main__":
    main()
