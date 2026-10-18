# Rider Intake Agent

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3) ![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Part of the waiting-room triage system. Takes a new patient intake and returns (1) the context rules that apply from the reviewed table (age, medications, complaint) and (2) a lookup of any condition the nurse typed against the NLM Clinical Tables vocabulary. For each real condition it asks the **Rider Evidence Agent** for a drafted rule and returns everything in one reply. Used by the backend and the triage coordinator; not meant for direct chat.
