"""
Seed data for the perioperative protocol knowledge base (protocol_db.py).

IMPORTANT — CLINICAL CONTENT STATUS
-----------------------------------
Every row below is seeded with requires_verification=1. The text is a
structural placeholder drafted from widely known perioperative device
management principles; phone numbers, magnet rates, FDA product codes, and
guideline citations MUST be verified by a clinician/implementer against the
cited guideline, the FDA product classification database, and current
manufacturer labeling before this content is relied on. Rows are only to be
flipped to requires_verification=0 by a reviewer, never by code.

Seeding is version-gated via kb_meta.seed_version: bumping SEED_VERSION wipes
and re-inserts all content tables in one transaction. Safe under the
single-worker gunicorn config; with multiple workers this would need a
BEGIN IMMEDIATE lock around the version check + reseed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import protocol_db
import device_class_resolver

SEED_VERSION = "2026.09.1"

_VERIFY = "VERIFY: placeholder pending clinician review"

# ---------------------------------------------------------------------------
# Device classes
# ---------------------------------------------------------------------------

DEVICE_CLASSES = [
    # (class_key, display_name, module, description)
    ("pacemaker", "Implantable pacemaker", "cardiac_rhythm",
     "Transvenous permanent pacemaker pulse generator"),
    ("leadless_pacemaker", "Leadless pacemaker", "cardiac_rhythm",
     "Intracardiac leadless pacemaker (e.g. Micra, Aveir)"),
    ("icd", "Implantable cardioverter-defibrillator (ICD)", "cardiac_rhythm",
     "Transvenous or subcutaneous ICD"),
    ("crt_p", "Cardiac resynchronization therapy pacemaker (CRT-P)", "cardiac_rhythm",
     "Biventricular pacemaker without defibrillation"),
    ("crt_d", "Cardiac resynchronization therapy defibrillator (CRT-D)", "cardiac_rhythm",
     "Biventricular pacing with defibrillation"),
    ("vns", "Vagus nerve stimulator (VNS)", "neuromodulation",
     "Implanted vagus nerve stimulation system"),
    ("dbs", "Deep brain stimulator (DBS)", "neuromodulation",
     "Deep brain stimulation system (IPG + intracranial leads)"),
    ("scs", "Spinal cord stimulator (SCS)", "neuromodulation",
     "Spinal cord stimulation system for chronic pain"),
    ("insulin_pump", "Insulin pump", "diabetes",
     "Continuous subcutaneous insulin infusion pump (standalone)"),
    ("cgm", "Continuous glucose monitor (CGM)", "diabetes",
     "Continuous glucose monitoring sensor/transmitter (standalone)"),
    ("closed_loop", "Closed-loop insulin delivery (AID)", "diabetes",
     "Hybrid closed-loop automated insulin delivery: pump + CGM + algorithm"),
]

# ---------------------------------------------------------------------------
# Resolution rules
# (class_key, rule_type, value, priority, notes)
# rule_type: fda_product_code | gmdn_code | gmdn_name_keyword | type_keyword | brand_keyword
# FDA product codes are CANDIDATES — verify each via
#   https://api.fda.gov/device/classification.json?search=product_code:XXX
# ---------------------------------------------------------------------------

RESOLUTION_RULES = [
    # FDA product codes (high confidence when verified)
    ("pacemaker", "fda_product_code", "DXY", 10, "VERIFY: implantable pacemaker pulse generator"),
    ("pacemaker", "fda_product_code", "NVZ", 11, "VERIFY: MR-conditional pacemaker"),
    ("leadless_pacemaker", "fda_product_code", "PNJ", 10, "VERIFY: leadless pacemaker"),
    ("icd", "fda_product_code", "LWS", 10, "VERIFY: automatic implantable cardioverter-defibrillator"),
    ("icd", "fda_product_code", "MRM", 11, "VERIFY: subcutaneous ICD candidate code"),
    ("crt_d", "fda_product_code", "NIK", 10, "VERIFY: CRT-D"),
    ("crt_p", "fda_product_code", "NKE", 10, "VERIFY: CRT-P"),
    ("dbs", "fda_product_code", "MHY", 10, "VERIFY: implanted deep brain stimulator (tremor code; PD/other indications may carry different codes)"),
    ("scs", "fda_product_code", "LGW", 10, "VERIFY: totally implanted spinal cord stimulator"),
    ("insulin_pump", "fda_product_code", "LZG", 10, "VERIFY: insulin infusion pump"),
    ("insulin_pump", "fda_product_code", "OPP", 11, "VERIFY: alternate controller enabled (ACE) infusion pump"),
    ("cgm", "fda_product_code", "QBJ", 10, "VERIFY: integrated CGM (iCGM)"),
    ("cgm", "fda_product_code", "MDS", 11, "VERIFY: legacy CGM candidate code"),
    # VNS product code intentionally omitted — implementer must look it up
    # (LivaNova VNS Therapy PMA); GMDN keyword + brand rules cover it meanwhile.

    # GMDN PT name / type keywords (medium confidence)
    ("crt_d", "gmdn_name_keyword", "cardiac resynchroni", 18,
     "before generic defibrillator/pacemaker keywords; CRT-D vs CRT-P split needs brand/code"),
    ("leadless_pacemaker", "gmdn_name_keyword", "leadless pacemaker", 19, None),
    ("pacemaker", "gmdn_name_keyword", "cardiac pacemaker", 20, None),
    ("icd", "gmdn_name_keyword", "cardioverter defibrillator", 20, None),
    ("icd", "gmdn_name_keyword", "implantable defibrillator", 21, None),
    ("vns", "gmdn_name_keyword", "vagus nerve stimulat", 20, None),
    ("vns", "gmdn_name_keyword", "vagal nerve stimulat", 21, None),
    ("dbs", "gmdn_name_keyword", "deep brain stimulat", 20, None),
    ("scs", "gmdn_name_keyword", "spinal cord stimulat", 20, None),
    ("insulin_pump", "gmdn_name_keyword", "insulin infusion pump", 20, None),
    ("insulin_pump", "gmdn_name_keyword", "insulin pump", 21, None),
    ("cgm", "gmdn_name_keyword", "continuous glucose", 20, None),

    # Free-text fallback (low confidence)
    ("pacemaker", "type_keyword", "pacemaker", 90, "low-confidence fallback"),
    ("icd", "type_keyword", "defibrillat", 90,
     "low-confidence fallback; also matches wearable/external defibrillators"),
]

# ---------------------------------------------------------------------------
# Brand/model rules — checked FIRST; the only way to detect closed-loop AID.
# (manufacturer_pattern, brand_pattern, resolves_class, priority, notes)
# Patterns are case-insensitive substrings; avoid manufacturer-only rules
# (e.g. LivaNova also makes cardiopulmonary products).
# ---------------------------------------------------------------------------

BRAND_MODEL_RULES = [
    # Closed-loop AID systems (VERIFY model lists)
    ("tandem", "control-iq", "closed_loop", 10, "VERIFY: Tandem Control-IQ"),
    ("tandem", "t:slim x2", "closed_loop", 11, "VERIFY: t:slim X2 ships with Control-IQ"),
    ("medtronic", "780g", "closed_loop", 10, "VERIFY: MiniMed 780G SmartGuard"),
    ("medtronic", "770g", "closed_loop", 11, "VERIFY: MiniMed 770G SmartGuard"),
    ("medtronic", "670g", "closed_loop", 12, "VERIFY: MiniMed 670G SmartGuard"),
    ("insulet", "omnipod 5", "closed_loop", 10, "VERIFY: Omnipod 5 automated mode"),
    (None, "omnipod 5", "closed_loop", 13, "VERIFY: manufacturer string may differ"),
    ("beta bionics", "ilet", "closed_loop", 10, "VERIFY: iLet bionic pancreas"),
    # CGM brands (VERIFY)
    ("dexcom", None, "cgm", 20, "VERIFY: Dexcom G6/G7"),
    ("abbott", "freestyle libre", "cgm", 20, "VERIFY: FreeStyle Libre family"),
    ("medtronic", "guardian", "cgm", 20, "VERIFY: Guardian sensor"),
    # Pump brands (VERIFY)
    ("medtronic", "minimed", "insulin_pump", 30, "VERIFY: plain MiniMed pumps; 6xx/7xxG handled above"),
    # Cardiac rhythm brand families (VERIFY)
    ("medtronic", "micra", "leadless_pacemaker", 30, "VERIFY"),
    ("abbott", "aveir", "leadless_pacemaker", 30, "VERIFY"),
    ("medtronic", "azure", "pacemaker", 31, "VERIFY"),
    ("boston scientific", "accolade", "pacemaker", 31, "VERIFY"),
    ("abbott", "assurity", "pacemaker", 31, "VERIFY"),
    ("biotronik", "edora", "pacemaker", 31, "VERIFY"),
    ("medtronic", "evera", "icd", 31, "VERIFY"),
    ("medtronic", "cobalt", "icd", 31, "VERIFY"),
    ("abbott", "gallant", "icd", 31, "VERIFY"),
    ("boston scientific", "emblem", "icd", 31, "VERIFY: S-ICD (subcutaneous)"),
    # Neuromodulation brand families (VERIFY)
    ("livanova", "sentiva", "vns", 30, "VERIFY"),
    ("livanova", "aspiresr", "vns", 30, "VERIFY"),
    ("livanova", "demipulse", "vns", 30, "VERIFY"),
    ("cyberonics", "vns therapy", "vns", 30, "VERIFY: legacy company name"),
    ("medtronic", "percept", "dbs", 30, "VERIFY"),
    ("medtronic", "activa", "dbs", 30, "VERIFY"),
    ("boston scientific", "vercise", "dbs", 30, "VERIFY"),
    ("abbott", "infinity", "dbs", 32, "VERIFY: Abbott Infinity DBS; generic word, manufacturer-scoped"),
    ("medtronic", "intellis", "scs", 30, "VERIFY"),
    ("boston scientific", "wavewriter", "scs", 30, "VERIFY"),
    ("abbott", "proclaim", "scs", 30, "VERIFY"),
]

# ---------------------------------------------------------------------------
# Protocol facts
# (class_key, context, fact_key, fact_value, detail, severity,
#  guideline_source, guideline_year, citation)
# ---------------------------------------------------------------------------

_HRS_ASA = "HRS/ASA Expert Consensus Statement on perioperative CIED management (Crossley et al.)"
_HRS_ASA_CIT = "VERIFY exact citation: Crossley GH et al., Heart Rhythm 2011; and ASA Practice Advisory (Anesthesiology, 2020 update)"
_NBG_CIT = "VERIFY exact citation: Bernstein AD et al., The revised NASPE/BPEG generic code, PACE 2002"

PROTOCOL_FACTS = [
    # ----- pacemaker -----
    ("pacemaker", "surgery", "headline",
     "Determine pacing dependence before incision; have a magnet available in the room.",
     None, "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("pacemaker", "all", "magnet_behavior",
     "Magnet application switches most transvenous pacemakers to asynchronous pacing at a manufacturer-specific magnet rate while applied.",
     "Magnet rate varies by manufacturer and battery status (see brand info). Removing the magnet restores the programmed mode. Response can be programmed off in some devices — confirm at interrogation.",
     "caution", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("pacemaker", "all", "pacer_dependence",
     "Pacing dependence CANNOT be determined from the UDI, and is not settled by the programmed mode either. Check the most recent interrogation or EP note, and confirm clinically.",
     "Devices are commonly programmed to on-demand pacing even in patients with no intrinsic escape rhythm, so an on-demand mode does not exclude dependence. Where dependence is not established and significant electromagnetic interference is expected (e.g. monopolar cautery above the umbilicus), treat the patient as potentially dependent and plan asynchronous pacing per institutional policy.",
     "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("pacemaker", "surgery", "electrocautery",
     "Prefer bipolar electrocautery. If monopolar is required, use short irregular bursts and place the dispersive electrode so the current path avoids the generator and leads.",
     "Risk of oversensing/inhibition is highest for surgical sites above the umbilicus.",
     "caution", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("pacemaker", "all", "nbg_semantics",
     "NBG code (e.g. DDD, VVIR): I = chamber paced, II = chamber sensed, III = response to sensing, IV = rate modulation, V = multisite pacing.",
     "The programmed mode is NOT in GUDID — it comes from the device interrogation. This entry explains how to read the mode once known.",
     "info", "NASPE/BPEG revised generic code (Bernstein et al.)", "2002", _NBG_CIT),
    ("pacemaker", "mri", "mri",
     "MR-conditional status is model- AND system-specific (generator plus all leads). Confirm the full system against labeling and the institutional EP device list.",
     "Scanning typically requires the institutional CIED-MRI protocol: pre-scan programming to an MRI mode, monitoring during scan, and post-scan re-programming/interrogation.",
     "caution", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("pacemaker", "all", "support_phone",
     "Call the manufacturer's 24-hr CRM technical support line (brand-specific number shown when known).",
     None, "info", None, None, _VERIFY),

    # ----- leadless pacemaker -----
    ("leadless_pacemaker", "surgery", "headline",
     "Leadless pacemakers do NOT respond to magnet application — reprogramming requires a programmer.",
     None, "critical", None, None,
     "VERIFY against Medtronic Micra / Abbott Aveir manuals — no magnet sensor"),
    ("leadless_pacemaker", "all", "magnet_behavior",
     "No magnet response: leadless pacemakers (e.g. Micra, Aveir) have no magnet sensor; asynchronous pacing requires reprogramming with the manufacturer programmer.",
     None, "critical", None, None,
     "VERIFY against manufacturer technical manuals"),
    ("leadless_pacemaker", "all", "pacer_dependence",
     "Pacing dependence CANNOT be determined from the UDI. Check the most recent device interrogation or EP note.",
     "If dependent and EMI is expected, arrange device reprogramming — a magnet is not an option for these devices.",
     "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("leadless_pacemaker", "surgery", "electrocautery",
     "Prefer bipolar electrocautery; with monopolar use short bursts and keep the current path away from the heart.",
     None, "caution", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("leadless_pacemaker", "mri", "mri",
     "Commonly MR-conditional, but conditions are model-specific — confirm labeling and follow the institutional CIED-MRI protocol.",
     None, "caution", None, None, _VERIFY),
    ("leadless_pacemaker", "all", "support_phone",
     "Call the manufacturer's 24-hr CRM technical support line (brand-specific number shown when known).",
     None, "info", None, None, _VERIFY),

    # ----- icd -----
    ("icd", "surgery", "headline",
     "Magnet suspends shock therapy but does NOT change pacing — keep an external defibrillator immediately available.",
     None, "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("icd", "all", "magnet_behavior",
     "Magnet application suspends tachyarrhythmia detection/therapy (shocks, ATP) while applied; it does NOT switch pacing to asynchronous mode.",
     "If the patient is also pacing-dependent, asynchronous pacing requires reprogramming. Magnet response can be programmed off in some devices — confirm at interrogation. Subcutaneous ICDs (e.g. Emblem S-ICD) have their own magnet behavior — verify per model.",
     "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("icd", "all", "pacer_dependence",
     "Pacing dependence CANNOT be determined from the UDI. Check the most recent device interrogation or EP note.",
     "A magnet alone is insufficient for a pacing-dependent ICD patient facing significant EMI — reprogramming is needed for asynchronous pacing.",
     "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("icd", "surgery", "electrocautery",
     "Suspend tachyarrhythmia therapy (magnet or reprogramming) before monopolar cautery, especially above the umbilicus; restore and re-interrogate post-op.",
     "Prefer bipolar; with monopolar use short bursts and route the dispersive-pad current path away from the generator and leads. External defibrillation must be immediately available while therapy is suspended.",
     "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("icd", "mri", "mri",
     "MR-conditional status is model- AND system-specific (generator plus all leads). Confirm the full system against labeling and the institutional EP device list.",
     "Tachyarrhythmia therapy is programmed off during the scan per protocol — continuous monitoring and immediate external defibrillation availability are required.",
     "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("icd", "ep_study", "mode_guidance",
     "For cardioversion/defibrillation or EP procedures, place pads/paddles as far from the generator as practical and interrogate the device afterward.",
     None, "caution", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("icd", "all", "support_phone",
     "Call the manufacturer's 24-hr CRM technical support line (brand-specific number shown when known).",
     None, "info", None, None, _VERIFY),

    # ----- crt_p (paces like a pacemaker) -----
    ("crt_p", "surgery", "headline",
     "CRT-P behaves like a pacemaker under magnet; biventricular patients are often pacing-dependent — verify dependence.",
     None, "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("crt_p", "all", "magnet_behavior",
     "Magnet application switches the CRT-P to asynchronous pacing at the manufacturer-specific magnet rate while applied (as for a standard pacemaker).",
     None, "caution", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("crt_p", "all", "pacer_dependence",
     "Pacing dependence CANNOT be determined from the UDI — and CRT patients depend on continuous biventricular pacing for hemodynamic benefit. Check the latest interrogation.",
     None, "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("crt_p", "surgery", "electrocautery",
     "Prefer bipolar electrocautery; with monopolar use short bursts and keep the dispersive-pad current path away from the generator and leads.",
     None, "caution", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("crt_p", "mri", "mri",
     "MR-conditional status is system-specific (generator plus all three leads). Confirm against labeling and the institutional EP device list.",
     None, "caution", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("crt_p", "all", "support_phone",
     "Call the manufacturer's 24-hr CRM technical support line (brand-specific number shown when known).",
     None, "info", None, None, _VERIFY),

    # ----- crt_d (shocks like an ICD) -----
    ("crt_d", "surgery", "headline",
     "Magnet suspends shocks but NOT pacing; CRT-D patients are frequently pacing-dependent — plan both therapy suspension and pacing strategy.",
     None, "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("crt_d", "all", "magnet_behavior",
     "Magnet application suspends tachyarrhythmia therapy while applied; it does NOT alter biventricular pacing mode or rate.",
     "Asynchronous pacing for a dependent patient requires reprogramming.",
     "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("crt_d", "all", "pacer_dependence",
     "Pacing dependence CANNOT be determined from the UDI — and CRT patients depend on continuous biventricular pacing. Check the latest interrogation.",
     None, "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("crt_d", "surgery", "electrocautery",
     "Suspend tachyarrhythmia therapy (magnet or reprogramming) before monopolar cautery; keep external defibrillation immediately available; re-interrogate post-op.",
     None, "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("crt_d", "mri", "mri",
     "MR-conditional status is system-specific (generator plus all leads). Confirm against labeling and the institutional EP device list; therapy is programmed off during the scan per protocol.",
     None, "critical", _HRS_ASA, "2011/2020", _HRS_ASA_CIT),
    ("crt_d", "all", "support_phone",
     "Call the manufacturer's 24-hr CRM technical support line (brand-specific number shown when known).",
     None, "info", None, None, _VERIFY),

    # ----- vns -----
    ("vns", "surgery", "headline",
     "Coordinate with neurology: VNS output is typically programmed OFF (0 mA) before surgery with electrocautery near the device.",
     None, "critical", None, None,
     "VERIFY against LivaNova VNS Therapy physician's manual"),
    ("vns", "all", "magnet_behavior",
     "Holding the patient magnet over the generator inhibits stimulation while held; a brief swipe triggers an extra stimulation burst on magnet-mode/AutoStim models.",
     "Magnet semantics are the opposite of intuition for many staff — holding inhibits, swiping stimulates. Confirm model-specific behavior.",
     "caution", None, None, "VERIFY against LivaNova VNS Therapy physician's manual"),
    ("vns", "surgery", "mode_guidance",
     "Pre-procedure: confirm with the managing neurologist whether to program output to 0 mA, rely on magnet inhibition, or leave settings untouched for short procedures away from the device.",
     "Document who will restore settings post-op and how the patient's seizure plan is covered while stimulation is off.",
     "caution", None, None, _VERIFY),
    ("vns", "surgery", "electrocautery",
     "Electrocautery near the generator or lead can damage the device or injure the nerve — program output off and keep the dispersive-pad current path away from the system.",
     None, "critical", None, None, "VERIFY against LivaNova VNS Therapy physician's manual"),
    ("vns", "mri", "mode_guidance",
     "MRI requires model-specific conditions: output is typically programmed to 0 mA before the scan and restored after; transmit/receive coil and anatomy restrictions apply.",
     "Check the exact generator and lead model against the LivaNova MRI guidelines before scheduling.",
     "critical", None, None, "VERIFY against LivaNova VNS Therapy MRI guidelines"),
    ("vns", "ep_study", "mode_guidance",
     "Cardioversion/defibrillation and ablation energy can damage the generator or lead — place pads as far from the system as practical and verify function afterward.",
     None, "caution", None, None, _VERIFY),
    ("vns", "all", "support_phone",
     "Call the manufacturer's 24-hr technical support line (brand-specific number shown when known).",
     None, "info", None, None, _VERIFY),

    # ----- dbs -----
    ("dbs", "surgery", "headline",
     "Coordinate with the DBS team: stimulation is typically turned OFF before monopolar electrocautery; expect symptom return (tremor, rigidity) while off.",
     None, "critical", None, None,
     "VERIFY against manufacturer DBS manuals (Medtronic/Boston Scientific/Abbott)"),
    ("dbs", "surgery", "mode_guidance",
     "Pre-procedure: confirm who turns stimulation off and on (patient controller vs programmer), and whether the patient can tolerate being off.",
     "Abrupt cessation can cause significant symptom rebound in Parkinson disease — plan timing with neurology.",
     "caution", None, None, _VERIFY),
    ("dbs", "surgery", "electrocautery",
     "Monopolar electrocautery can couple into DBS leads and injure brain tissue or damage the IPG — turn stimulation off, prefer bipolar, and keep the current path away from the system.",
     None, "critical", None, None, "VERIFY against manufacturer DBS manuals"),
    ("dbs", "mri", "mode_guidance",
     "MRI eligibility and the required MRI mode differ by manufacturer and full system (IPG + extensions + leads). Verify the exact models against the manufacturer's MRI guidelines before scheduling.",
     "Some systems allow full-body 1.5T/3T scanning in MRI mode; others are head-only or excluded (brand-specific notes shown when known).",
     "critical", None, None, "VERIFY against manufacturer MRI guidelines"),
    ("dbs", "ep_study", "mode_guidance",
     "Cardioversion/defibrillation can damage the IPG or injure tissue via the leads — place pads as far from the system as practical, use the lowest effective energy, and verify function afterward.",
     None, "critical", None, None, _VERIFY),
    ("dbs", "all", "support_phone",
     "Call the manufacturer's 24-hr neuromodulation support line (brand-specific number shown when known).",
     None, "info", None, None, _VERIFY),

    # ----- scs -----
    ("scs", "surgery", "headline",
     "Turn spinal cord stimulation OFF before surgery with electrocautery; confirm the patient has their controller available for post-op reactivation.",
     None, "critical", None, None, "VERIFY against manufacturer SCS manuals"),
    ("scs", "surgery", "mode_guidance",
     "Pre-procedure: stimulation off (patient remote usually suffices); document baseline settings or confirm the patient/rep can restore them.",
     None, "caution", None, None, _VERIFY),
    ("scs", "surgery", "electrocautery",
     "Electrocautery can couple into epidural leads — turn stimulation off, prefer bipolar, and keep the dispersive-pad current path away from the generator and leads.",
     None, "critical", None, None, "VERIFY against manufacturer SCS manuals"),
    ("scs", "mri", "mode_guidance",
     "Many modern SCS systems have MRI-conditional modes, but conditions are model- and lead-specific — verify the exact system against manufacturer MRI guidelines and enable MRI mode before the scan.",
     None, "critical", None, None, "VERIFY against manufacturer MRI guidelines"),
    ("scs", "ep_study", "mode_guidance",
     "Cardioversion/defibrillation and ablation energy can damage the system — place pads away from the generator/leads and verify function afterward.",
     None, "caution", None, None, _VERIFY),
    ("scs", "all", "support_phone",
     "Call the manufacturer's 24-hr neuromodulation support line (brand-specific number shown when known).",
     None, "info", None, None, _VERIFY),

    # ----- insulin_pump -----
    ("insulin_pump", "surgery", "headline",
     "Decide pre-op: continue basal-only or disconnect and bridge with IV/SC insulin — and verify the infusion site is away from the surgical and cautery field.",
     None, "critical", None, None,
     "VERIFY against institutional perioperative diabetes-technology policy"),
    ("insulin_pump", "surgery", "mode_guidance",
     "If continuing the pump: basal-only (no boluses under anesthesia), site checked and secured, pump accessible to the anesthesia team, and a plan for hypo/hyperglycemia.",
     "If disconnecting: start alternative insulin coverage before disconnection for insulin-dependent patients — pump insulin is rapid-acting and DKA can develop within hours.",
     "critical", None, None, _VERIFY),
    ("insulin_pump", "surgery", "electrocautery",
     "Keep the pump and infusion set out of the dispersive-pad current path; relocate the site pre-op if it is near the surgical or cautery field.",
     None, "caution", None, None, _VERIFY),
    ("insulin_pump", "mri", "mri",
     "Insulin pumps are generally NOT MR-safe — remove the pump (and per labeling, the infusion set's metal components) before the patient enters the MRI suite.",
     "Plan alternative insulin coverage for the time off-pump.",
     "critical", None, None, "VERIFY against pump labeling (manufacturer-specific)"),
    ("insulin_pump", "all", "support_phone",
     "Call the manufacturer's 24-hr support line (brand-specific number shown when known).",
     None, "info", None, None, _VERIFY),

    # ----- cgm -----
    ("cgm", "surgery", "headline",
     "Do NOT dose insulin from CGM values intra-op — electrocautery and imaging energy can produce falsely high or low readings. Confirm with blood glucose.",
     None, "critical", None, None,
     "VERIFY: locate exact FDA safety communication / manufacturer labeling text before attributing to FDA"),
    ("cgm", "surgery", "cgm_interference",
     "Electrocautery/diathermy and ionizing imaging can produce falsely high or low sensor glucose readings; treat CGM values as unreliable during and immediately after exposure.",
     "Manufacturer labeling warns against relying on sensor readings during diathermy/electrocautery and MRI/CT. Use blood glucose measurements for any treatment decision intra-op.",
     "critical", None, None,
     "VERIFY: exact FDA safety communication and Dexcom G6/G7 / FreeStyle Libre / Guardian labeling text"),
    ("cgm", "mri", "mri",
     "Remove the CGM sensor and transmitter before MRI (and per labeling for CT/diathermy) — sensors are generally not rated for these exposures and a removed sensor cannot be reattached.",
     "Bring a replacement sensor for after the scan.",
     "critical", None, None, "VERIFY against sensor labeling (manufacturer-specific)"),
    ("cgm", "all", "support_phone",
     "Call the manufacturer's 24-hr support line (brand-specific number shown when known).",
     None, "info", None, None, _VERIFY),

    # ----- closed_loop -----
    ("closed_loop", "surgery", "headline",
     "Automated insulin delivery may continue SILENTLY under anesthesia, driven by a CGM that is unreliable intra-op. Decide pre-op: suspend automation, switch to manual mode, or disconnect.",
     None, "critical", None, None,
     "VERIFY against institutional perioperative diabetes-technology policy and AID labeling"),
    ("closed_loop", "surgery", "closed_loop_note",
     "This is a hybrid closed-loop (AID) system: the pump doses insulin automatically from CGM input. Under anesthesia the patient cannot notice or correct algorithm-driven dosing errors.",
     "Pre-op decision points: (1) suspend automation / switch to manual or sleep-safe basal mode, (2) or disconnect entirely with alternative insulin coverage; (3) check blood glucose at defined intervals regardless of CGM display.",
     "critical", None, None, _VERIFY),
    ("closed_loop", "surgery", "cgm_interference",
     "The CGM driving this system is subject to electrocautery/imaging interference — falsely high readings can drive automated insulin over-delivery; falsely low readings suspend basal.",
     "Do not dose or trust automation from CGM values intra-op; confirm with blood glucose.",
     "critical", None, None,
     "VERIFY: exact FDA safety communication and manufacturer labeling text"),
    ("closed_loop", "surgery", "electrocautery",
     "Keep pump and sensor out of the dispersive-pad current path; if cautery is near either component, plan to disconnect/remove per labeling.",
     None, "caution", None, None, _VERIFY),
    ("closed_loop", "mri", "mri",
     "Remove BOTH the pump and the CGM sensor/transmitter before MRI — neither component is MR-safe. Plan alternative insulin coverage and a replacement sensor.",
     None, "critical", None, None, "VERIFY against pump and sensor labeling"),
    ("closed_loop", "all", "support_phone",
     "Call the manufacturer's 24-hr support line (brand-specific number shown when known).",
     None, "info", None, None, _VERIFY),
]

# ---------------------------------------------------------------------------
# Checklists
# (class_key, context, position, item_text, rationale, guideline_source, citation)
# ---------------------------------------------------------------------------

CHECKLISTS = [
    # ----- pacemaker / crt_p (surgery) -----
    *[
        (ck, "surgery", pos, text, rationale, _HRS_ASA, _HRS_ASA_CIT)
        for ck in ("pacemaker", "crt_p")
        for pos, text, rationale in [
            (1, "Confirm device manufacturer and model (this scan) and locate the most recent interrogation report.",
             "Magnet behavior and reprogramming options are manufacturer-specific."),
            (2, "Determine pacing dependence from the interrogation/EP note — not from the UDI.",
             "Dependence drives whether asynchronous pacing must be arranged."),
            (3, "Check for an active recall on this device (shown above if flagged)." , None),
            (4, "Decide EMI strategy: magnet vs pre-op reprogramming, based on dependence, procedure site, and cautery plan.",
             "Magnet gives asynchronous pacing in most pacemakers; reprogramming is definitive."),
            (5, "Confirm a magnet is physically available in the operating room.", None),
            (6, "Agree cautery plan with the surgeon: bipolar preferred; monopolar in short bursts with dispersive pad away from the generator/leads.", None),
            (7, "Define post-op check criteria: interrogation if the device was reprogrammed, magnet-exposed with concerns, or cautery was used near the generator.", None),
        ]
    ],
    # ----- leadless pacemaker (surgery) -----
    ("leadless_pacemaker", "surgery", 1,
     "Confirm device model; remember: NO magnet response — reprogramming needs the manufacturer programmer.",
     "Leadless devices have no magnet sensor.", None, "VERIFY manufacturer manuals"),
    ("leadless_pacemaker", "surgery", 2,
     "Determine pacing dependence from the latest interrogation.", None, _HRS_ASA, _HRS_ASA_CIT),
    ("leadless_pacemaker", "surgery", 3,
     "If dependent and EMI expected: arrange device-rep/EP reprogramming pre-op — a magnet will not help.",
     None, None, _VERIFY),
    ("leadless_pacemaker", "surgery", 4,
     "Cautery plan: bipolar preferred; monopolar short bursts, current path away from the heart.",
     None, _HRS_ASA, _HRS_ASA_CIT),
    ("leadless_pacemaker", "surgery", 5,
     "Define post-op interrogation criteria with EP.", None, _HRS_ASA, _HRS_ASA_CIT),
    # ----- icd / crt_d (surgery) -----
    *[
        (ck, "surgery", pos, text, rationale, _HRS_ASA, _HRS_ASA_CIT)
        for ck in ("icd", "crt_d")
        for pos, text, rationale in [
            (1, "Confirm device manufacturer and model (this scan) and locate the most recent interrogation report.", None),
            (2, "Determine pacing dependence — a magnet suspends shocks but does NOT provide asynchronous pacing.",
             "Dependent patients need reprogramming, not just a magnet."),
            (3, "Check for an active recall on this device (shown above if flagged).", None),
            (4, "Decide therapy-suspension strategy: magnet on the sterile field plan vs pre-op reprogramming.", None),
            (5, "Place external defibrillation pads BEFORE suspending tachyarrhythmia therapy; keep the defibrillator immediately available.", None),
            (6, "Agree cautery plan: bipolar preferred; monopolar short bursts, dispersive pad away from generator/leads.", None),
            (7, "Restore tachyarrhythmia therapy (remove magnet / reprogram) before leaving monitored care; interrogate per institutional criteria.", None),
        ]
    ],
    # ----- cardiac MRI checklists -----
    *[
        (ck, "mri", pos, text, None, _HRS_ASA, _HRS_ASA_CIT)
        for ck in ("pacemaker", "leadless_pacemaker", "icd", "crt_p", "crt_d")
        for pos, text in [
            (1, "Identify the FULL implanted system (generator AND all leads, including abandoned leads) — MR conditions apply to the system, not the generator alone."),
            (2, "Check the institutional EP device list / manufacturer labeling for MR-conditional status and field-strength conditions."),
            (3, "Schedule under the institutional CIED-MRI protocol: pre-scan programming, monitoring during scan, post-scan interrogation."),
        ]
    ],
    # ----- cardiac EP-study checklists -----
    *[
        (ck, "ep_study", pos, text, None, _HRS_ASA, _HRS_ASA_CIT)
        for ck in ("pacemaker", "leadless_pacemaker", "icd", "crt_p", "crt_d")
        for pos, text in [
            (1, "Place cardioversion/defibrillation pads as far from the generator as practical (anterior-posterior preferred)."),
            (2, "Interrogate the device after any cardioversion, defibrillation, or ablation energy delivery."),
        ]
    ],
    # ----- vns (surgery) -----
    ("vns", "surgery", 1,
     "Identify the VNS model and the managing neurologist; confirm indication (epilepsy vs depression).",
     None, None, _VERIFY),
    ("vns", "surgery", 2,
     "Confirm the pre-procedure plan: program output to 0 mA, rely on magnet inhibition, or leave untouched (short cases away from the device).",
     None, None, "VERIFY LivaNova physician's manual"),
    ("vns", "surgery", 3,
     "If relying on the magnet: confirm staff know HOLDING inhibits and SWIPING triggers stimulation.",
     "Magnet semantics are commonly misunderstood.", None, "VERIFY LivaNova physician's manual"),
    ("vns", "surgery", 4,
     "Cautery plan: keep current path away from the generator and lead; output off for cautery near the device.",
     None, None, _VERIFY),
    ("vns", "surgery", 5,
     "Document who restores settings post-op and the seizure coverage plan while stimulation is off.",
     None, None, _VERIFY),
    # ----- vns (mri) -----
    ("vns", "mri", 1,
     "Check the exact generator and lead model against LivaNova MRI guidelines (coil type, anatomy, field strength).",
     None, None, "VERIFY LivaNova MRI guidelines"),
    ("vns", "mri", 2,
     "Arrange pre-scan programming (typically output 0 mA) and post-scan restoration by a qualified provider.",
     None, None, _VERIFY),
    # ----- dbs (surgery) -----
    ("dbs", "surgery", 1,
     "Identify the DBS system (IPG model + lead models) and the managing movement-disorder/neurosurgery team.",
     None, None, _VERIFY),
    ("dbs", "surgery", 2,
     "Confirm the off/on plan: who turns stimulation off (patient controller vs programmer), when, and who restores it.",
     None, None, _VERIFY),
    ("dbs", "surgery", 3,
     "Anticipate symptom rebound while off (tremor, rigidity, dystonia) — plan timing and positioning accordingly.",
     None, None, _VERIFY),
    ("dbs", "surgery", 4,
     "Cautery plan: stimulation OFF before monopolar; bipolar preferred; dispersive pad away from the IPG and cranial leads.",
     None, None, "VERIFY manufacturer DBS manuals"),
    ("dbs", "surgery", 5,
     "Verify stimulation restored and patient at baseline before discharge from monitored care.",
     None, None, _VERIFY),
    # ----- dbs (mri) -----
    ("dbs", "mri", 1,
     "Verify the FULL system (IPG + extensions + leads) against the manufacturer's MRI eligibility tables.",
     None, None, "VERIFY manufacturer MRI guidelines"),
    ("dbs", "mri", 2,
     "Enable the system's MRI mode before the scan and restore therapy settings after.",
     None, None, _VERIFY),
    # ----- scs (surgery) -----
    ("scs", "surgery", 1,
     "Identify the SCS system and confirm the patient brought their controller/remote.",
     None, None, _VERIFY),
    ("scs", "surgery", 2,
     "Turn stimulation OFF pre-procedure (patient remote usually suffices); document baseline settings.",
     None, None, _VERIFY),
    ("scs", "surgery", 3,
     "Cautery plan: bipolar preferred; dispersive pad away from the generator and epidural leads.",
     None, None, "VERIFY manufacturer SCS manuals"),
    ("scs", "surgery", 4,
     "Reactivate post-op and confirm the patient's pain coverage plan.",
     None, None, _VERIFY),
    # ----- scs (mri) -----
    ("scs", "mri", 1,
     "Verify the exact system against manufacturer MRI guidelines; many systems require a specific MRI mode.",
     None, None, "VERIFY manufacturer MRI guidelines"),
    ("scs", "mri", 2,
     "Enable MRI mode before the scan; restore therapy after.",
     None, None, _VERIFY),
    # ----- insulin_pump (surgery) -----
    ("insulin_pump", "surgery", 1,
     "Decide and document: continue pump (basal-only) vs disconnect with IV/SC insulin bridge.",
     "Pump insulin is rapid-acting; insulin-dependent patients can develop DKA within hours off-pump without coverage.",
     None, _VERIFY),
    ("insulin_pump", "surgery", 2,
     "Inspect the infusion site: intact, secured, and away from the surgical/cautery field (relocate pre-op if not).",
     None, None, _VERIFY),
    ("insulin_pump", "surgery", 3,
     "If continuing: pump accessible to anesthesia, no boluses under anesthesia, and a hypo/hyperglycemia action plan.",
     None, None, _VERIFY),
    ("insulin_pump", "surgery", 4,
     "Check blood glucose at defined intervals intra-op regardless of pump status.",
     None, None, _VERIFY),
    ("insulin_pump", "mri", 1,
     "Remove the pump before the patient enters the MRI suite; plan insulin coverage for the time off-pump.",
     None, None, "VERIFY pump labeling"),
    # ----- cgm (surgery) -----
    ("cgm", "surgery", 1,
     "Confirm sensor location is away from the surgical field, dispersive pad, and warming devices.",
     None, None, _VERIFY),
    ("cgm", "surgery", 2,
     "Do NOT dose insulin from CGM values intra-op — use blood glucose for treatment decisions.",
     "Electrocautery/imaging can produce falsely high or low sensor readings.",
     None, "VERIFY FDA safety communication / manufacturer labeling"),
    ("cgm", "surgery", 3,
     "If the sensor must be removed (field/imaging), plan a replacement sensor post-op.",
     None, None, _VERIFY),
    ("cgm", "mri", 1,
     "Remove the CGM sensor and transmitter before MRI; bring a replacement for after the scan.",
     None, None, "VERIFY sensor labeling"),
    # ----- closed_loop (surgery) -----
    ("closed_loop", "surgery", 1,
     "Identify the AID system and algorithm (shown above when known) and whether automation is currently active.",
     None, None, _VERIFY),
    ("closed_loop", "surgery", 2,
     "Decide pre-op: suspend automation / switch to manual or exercise/sleep mode / disconnect entirely — per institutional policy.",
     "Automated dosing continues silently under anesthesia, driven by an interference-prone CGM.",
     None, _VERIFY),
    ("closed_loop", "surgery", 3,
     "Treat intra-op CGM values as unreliable: check blood glucose at defined intervals and act on those.",
     None, None, "VERIFY FDA safety communication / manufacturer labeling"),
    ("closed_loop", "surgery", 4,
     "Inspect pump site and sensor location relative to the surgical/cautery field.",
     None, None, _VERIFY),
    ("closed_loop", "surgery", 5,
     "Document the post-op plan: when automation resumes and who confirms settings.",
     None, None, _VERIFY),
    ("closed_loop", "mri", 1,
     "Remove BOTH pump and CGM sensor/transmitter before MRI; plan insulin coverage and a replacement sensor.",
     None, None, "VERIFY pump and sensor labeling"),
]

# ---------------------------------------------------------------------------
# Brand facts
# (manufacturer_pattern, brand_pattern, class_key, fact_key, fact_value, detail, citation)
# Support lines are class-scoped because manufacturers run separate lines per
# business unit (e.g. Medtronic CRM vs Medtronic Diabetes).
# ---------------------------------------------------------------------------

_CARDIAC_CLASSES = ("pacemaker", "leadless_pacemaker", "icd", "crt_p", "crt_d")

BRAND_FACTS = [
    # 24-hr CRM support lines (ALL numbers VERIFY)
    *[("medtronic", None, ck, "support_phone", "+1-800-723-4636",
       "Medtronic CRM 24-hr technical services", "VERIFY number") for ck in _CARDIAC_CLASSES],
    *[("abbott", None, ck, "support_phone", "+1-800-722-3774",
       "Abbott (St. Jude Medical) CRM 24-hr technical support", "VERIFY number") for ck in _CARDIAC_CLASSES],
    *[("st. jude", None, ck, "support_phone", "+1-800-722-3774",
       "Abbott (St. Jude Medical) CRM 24-hr technical support", "VERIFY number") for ck in _CARDIAC_CLASSES],
    *[("boston scientific", None, ck, "support_phone", "+1-800-227-3422",
       "Boston Scientific CRM 24-hr technical services (1-800-CARDIAC)", "VERIFY number") for ck in _CARDIAC_CLASSES],
    *[("biotronik", None, ck, "support_phone", "+1-800-547-0394",
       "Biotronik 24-hr technical support", "VERIFY number") for ck in _CARDIAC_CLASSES],

    # Pacemaker/CRT-P magnet rates by manufacturer (ALL VERIFY) — CRT-P paces
    # like a pacemaker under magnet, so it shares the rate rows.
    *[(mfr, None, ck, "magnet_rate", rate, detail, "VERIFY")
      for ck in ("pacemaker", "crt_p")
      for mfr, rate, detail in [
          ("medtronic", "85 bpm",
           "Medtronic pacemaker magnet rate at beginning of life; drops near elective replacement."),
          ("abbott", "98.6 bpm", "Abbott/St. Jude pacemaker magnet rate at beginning of life."),
          ("st. jude", "98.6 bpm", "Abbott/St. Jude pacemaker magnet rate at beginning of life."),
          ("boston scientific", "100 bpm", "Boston Scientific pacemaker magnet rate at beginning of life."),
          ("biotronik", "90 bpm",
           "Biotronik pacemaker magnet response (mode/rate is programmable on some models)."),
      ]],

    # Neuromodulation support lines (ALL VERIFY)
    ("livanova", None, "vns", "support_phone", "+1-866-882-8804",
     "LivaNova VNS Therapy 24-hr clinical/technical support", "VERIFY number"),
    ("cyberonics", None, "vns", "support_phone", "+1-866-882-8804",
     "LivaNova (Cyberonics) VNS Therapy support", "VERIFY number"),
    ("medtronic", None, "dbs", "support_phone", "+1-800-510-6735",
     "Medtronic Neuromodulation 24-hr support", "VERIFY number"),
    ("medtronic", None, "scs", "support_phone", "+1-800-510-6735",
     "Medtronic Neuromodulation 24-hr support", "VERIFY number"),
    ("abbott", None, "dbs", "support_phone", "+1-800-727-7846",
     "Abbott Neuromodulation support", "VERIFY number"),
    ("abbott", None, "scs", "support_phone", "+1-800-727-7846",
     "Abbott Neuromodulation support", "VERIFY number"),
    ("boston scientific", None, "dbs", "support_phone", "+1-866-789-6364",
     "Boston Scientific Neuromodulation support", "VERIFY number"),
    ("boston scientific", None, "scs", "support_phone", "+1-866-789-6364",
     "Boston Scientific Neuromodulation support", "VERIFY number"),

    # Diabetes support lines (ALL VERIFY)
    *[("medtronic", None, ck, "support_phone", "+1-800-646-4633",
       "Medtronic Diabetes 24-hr helpline", "VERIFY number") for ck in ("insulin_pump", "cgm", "closed_loop")],
    *[("tandem", None, ck, "support_phone", "+1-877-801-6901",
       "Tandem Diabetes Care 24-hr technical support", "VERIFY number") for ck in ("insulin_pump", "closed_loop")],
    *[("dexcom", None, ck, "support_phone", "+1-888-738-3646",
       "Dexcom 24-hr technical support", "VERIFY number") for ck in ("cgm", "closed_loop")],
    ("abbott", None, "cgm", "support_phone", "+1-855-632-8658",
     "Abbott Diabetes Care (FreeStyle Libre) customer care", "VERIFY number"),
    *[("insulet", None, ck, "support_phone", "+1-800-591-3455",
       "Insulet (Omnipod) 24-hr customer care", "VERIFY number") for ck in ("insulin_pump", "closed_loop")],

    # AID algorithm names (VERIFY)
    ("tandem", "control-iq", "closed_loop", "closed_loop_algorithm", "Control-IQ",
     "Tandem t:slim X2 with Control-IQ hybrid closed-loop algorithm.", "VERIFY"),
    ("medtronic", "780g", "closed_loop", "closed_loop_algorithm", "SmartGuard",
     "Medtronic MiniMed 780G SmartGuard with auto-corrections.", "VERIFY"),
    ("medtronic", "770g", "closed_loop", "closed_loop_algorithm", "SmartGuard",
     "Medtronic MiniMed 770G SmartGuard.", "VERIFY"),
    ("medtronic", "670g", "closed_loop", "closed_loop_algorithm", "SmartGuard",
     "Medtronic MiniMed 670G SmartGuard.", "VERIFY"),
    ("insulet", "omnipod 5", "closed_loop", "closed_loop_algorithm", "Omnipod 5 SmartAdjust",
     "Insulet Omnipod 5 automated insulin delivery.", "VERIFY"),
    ("beta bionics", "ilet", "closed_loop", "closed_loop_algorithm", "iLet bionic pancreas",
     "Beta Bionics iLet dosing algorithm.", "VERIFY"),
]


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def seed_protocols(db_path: Optional[Path] = None, force: bool = False) -> bool:
    """
    Idempotent, version-gated reseed. Returns True if a reseed ran.
    """
    conn = protocol_db.get_conn(db_path)
    try:
        protocol_db.init_db(conn)
        current = protocol_db.get_meta("seed_version", conn)
        if current == SEED_VERSION and not force:
            return False

        with conn:  # single transaction
            for table in protocol_db.CONTENT_TABLES:
                if table == "brand_facts":
                    # Only the seeded rows. Facts extracted from manufacturer
                    # manuals by the IFU pipeline are NOT seed data: they have
                    # their own provenance, cost an LLM call to produce, and are
                    # device-specific where seed rows are manufacturer-generic.
                    # Wiping them to refresh guideline content silently discarded
                    # them — e.g. the Azure's extracted 65 min-1 magnet rate,
                    # leaving the generic Medtronic 85 bpm showing in its place,
                    # which the Azure manual explicitly contradicts.
                    conn.execute("DELETE FROM brand_facts WHERE source != 'llm'")
                else:
                    conn.execute(f"DELETE FROM {table}")
            conn.executemany(
                "INSERT INTO device_classes (class_key, display_name, module, description) "
                "VALUES (?, ?, ?, ?)",
                DEVICE_CLASSES,
            )
            conn.executemany(
                "INSERT INTO class_resolution_rules (class_key, rule_type, value, priority, notes) "
                "VALUES (?, ?, ?, ?, ?)",
                RESOLUTION_RULES,
            )
            conn.executemany(
                "INSERT INTO brand_model_rules (manufacturer_pattern, brand_pattern, "
                "resolves_class, priority, notes) VALUES (?, ?, ?, ?, ?)",
                BRAND_MODEL_RULES,
            )
            conn.executemany(
                "INSERT INTO protocol_facts (class_key, context, fact_key, fact_value, detail, "
                "severity, guideline_source, guideline_year, citation) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                PROTOCOL_FACTS,
            )
            conn.executemany(
                "INSERT INTO checklist_items (class_key, context, position, item_text, "
                "rationale, guideline_source, citation) VALUES (?, ?, ?, ?, ?, ?, ?)",
                CHECKLISTS,
            )
            conn.executemany(
                "INSERT INTO brand_facts (manufacturer_pattern, brand_pattern, class_key, "
                "fact_key, fact_value, detail, citation) VALUES (?, ?, ?, ?, ?, ?, ?)",
                BRAND_FACTS,
            )
            conn.execute(
                "INSERT INTO kb_meta (key, value) VALUES ('seed_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (SEED_VERSION,),
            )
            conn.execute(
                "INSERT INTO kb_meta (key, value) VALUES ('seeded_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (datetime.now(timezone.utc).isoformat(),),
            )
        device_class_resolver.clear_cache()
        print(f"[protocol-seed] seeded knowledge base at version {SEED_VERSION}")
        return True
    finally:
        conn.close()
