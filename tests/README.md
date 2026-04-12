# Test Suite

This suite validates the production decision engine in business terms rather than the retired hackathon workflow.

Coverage summary:

- `test_intake.py`: business intake normalization and inferred targeting model construction.
- `test_interview.py`: capped six-step intake flow, structured answer extraction, and refinement behavior.
- `test_discovery.py`: seed URL handling and discovery adapter registration.
- `test_parsing.py`: deterministic HTML parsing for entity extraction inputs.
- `test_enrichment.py`: entity enrichment, contact-path creation, decision-maker inference, and exclusion handling.
- `test_scoring.py`: deterministic scoring plus bounded LLM refinement behavior.
- `test_matching.py`: final opportunity assembly, reasoning plumbing, and best-contact selection.
- `test_export.py`: Excel export structure for prioritized and skipped entities.
- `test_engine.py`: orchestration flow and pause/stop control behavior.
- `test_profile_flow.py`: framework-neutral profile parsing, summary-card shaping, and draft update helpers.
- `test_django_views.py`: Django session-backed research, edit, save, request-data, and Firebase login/logout flows.
- `test_firebase_auth.py`: Firebase token verification success and failure behavior.
- `test_session_state.py`: Django session serialization and workspace state lifecycle.
- `test_forms.py`: Django form normalization and coercion rules.
- `test_frontend_auth_contract.py`: frontend auth script contract for local redirect and popup fallback behavior.
- `test_validation.py`: email syntax and validation fallback behavior.
- `test_services.py`: fetch/search/OpenAI retry and fallback behavior.
- `test_cloud.py`: Cloud Run and Pub/Sub-facing integration helpers.
- `test_profile_research.py`: website-plus-search evidence gathering and GPT-backed profile draft generation.
- `test_storage_profiles.py`: Firestore profile persistence payload and document routing.
