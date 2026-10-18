# Rider Evidence Agent

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3) ![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Part of the waiting-room triage system. Given one real medical condition (an NLM code), it searches PubMed, has a model pick a vital and a preset step from a fixed limit menu (the model never writes a number), and keeps the pick only if code checks pass: the quoted passage must appear in at least two real abstracts and name the vital. Otherwise it abstains. Drafted limits move only the warning edge for one patient and are labeled unreviewed. Called by the **Rider Intake Agent**.
