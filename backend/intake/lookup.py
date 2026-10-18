"""Medication name to I4 drug class (small hardcoded table, not the full NHANES RXQ_DRUG list).
Use when turning typed medication names into drug_classes and unmatched_medications at intake.

Only the six I4 classes come out. No fuzzy matching: a misspelling stays unmatched, so the adjuster
reads it from the complaint. Route words (inhaler, cream, eye drops...) drop the steroid and
beta-blocker classes, per notes/adjuster-labeling-guide.md, but the name still counts as matched."""
import re

_CLASSES = {
    "beta_blocker": "metoprolol lopressor toprol metoprolol-tartrate metoprolol-succinate atenolol tenormin "
                    "propranolol inderal carvedilol coreg labetalol bisoprolol nadolol nebivolol bystolic "
                    "timolol sotalol",
    "ssri": "sertraline zoloft fluoxetine prozac citalopram celexa escitalopram lexapro paroxetine paxil "
            "fluvoxamine",
    "snri": "venlafaxine effexor duloxetine cymbalta desvenlafaxine pristiq levomilnacipran",
    "opioid": "oxycodone oxycontin percocet hydrocodone vicodin norco morphine methadone fentanyl "
              "fentanyl-patch hydromorphone dilaudid codeine tramadol ultram tapentadol buprenorphine "
              "oxymorphone",
    "corticosteroid": "prednisone prednisolone methylprednisolone medrol dexamethasone hydrocortisone "
                      "cortisone betamethasone triamcinolone",
    "immunosuppressant": "azathioprine imuran humira adalimumab tacrolimus prograf mycophenolate cellcept "
                         "cyclosporine methotrexate sirolimus etanercept enbrel infliximab remicade "
                         "tofacitinib rituximab",
}
# Known, but no relevant class: keeps everyday medications out of unmatched_medications.
# Flovent and fluticasone are inhaled-only steroids, so a bare brand name has no route word.
_NO_CLASS = ("metformin lisinopril furosemide albuterol tiotropium potassium potassium-chloride insulin "
             "insulin-glargine clopidogrel ondansetron prenatal-vitamin omeprazole levothyroxine glipizide "
             "losartan amlodipine ibuprofen naproxen acetaminophen aspirin atorvastatin simvastatin warfarin "
             "apixaban eliquis hydrochlorothiazide spironolactone gabapentin montelukast flovent fluticasone "
             "budesonide beclomethasone mometasone capecitabine")

_TABLE = {name.replace("-", " "): cls for cls, names in _CLASSES.items() for name in names.split()}
_KNOWN = {name.replace("-", " ") for name in _NO_CLASS.split()}
_ROUTE = {"inhaler", "inhaled", "nasal", "spray", "cream", "ointment", "eye", "drops"}
_DOSE = re.compile(r"\d+(\.\d+)?\s*(mg|mcg|g|ml)\b")
_NOISE = {"daily", "twice", "once", "bid", "tid", "qid", "qd", "prn", "nightly", "weekly", "day", "per",
          "every", "times", "xl", "er", "sr", "xr", "dosepak", "dose", "pak", "pack"}


def classify(medications: list[str]) -> tuple[list[str], list[str]]:
    """(drug_classes sorted and unique, unmatched names as typed, in order). Use when building I4."""
    classes, unmatched = set(), []
    for raw in medications:
        text = _DOSE.sub(" ", raw.lower())
        words = re.sub(r"[^a-z0-9/ ]", " ", text).split()
        route = any(w in _ROUTE for w in words)
        name = " ".join(w for w in words if w not in _ROUTE and w not in _NOISE)
        cls = _TABLE.get(name)
        if cls or name in _KNOWN:
            if cls and not (route and cls in ("corticosteroid", "beta_blocker")):
                classes.add(cls)
        else:
            unmatched.append(raw)
    return sorted(classes), unmatched
