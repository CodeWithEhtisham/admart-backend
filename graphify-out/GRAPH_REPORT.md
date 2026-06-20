# Graph Report - .  (2026-06-20)

## Corpus Check
- Corpus is ~20,851 words - fits in a single context window. You may not need a graph.

## Summary
- 122 nodes · 173 edges · 28 communities (7 shown, 21 thin omitted)
- Extraction: 88% EXTRACTED · 12% INFERRED · 0% AMBIGUOUS · INFERRED: 20 edges (avg confidence: 0.83)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Flux Client & Proxy Services|Flux Client & Proxy Services]]
- [[_COMMUNITY_REST API Template Endpoint|REST API Template Endpoint]]
- [[_COMMUNITY_Flux Image Generation Engine|Flux Image Generation Engine]]
- [[_COMMUNITY_FastAPI App & Schemas|FastAPI App & Schemas]]
- [[_COMMUNITY_API Design Principles & Best Practices|API Design Principles & Best Practices]]
- [[_COMMUNITY_Agent Architectural Skills|Agent Architectural Skills]]
- [[_COMMUNITY_Management Scripts|Management Scripts]]
- [[_COMMUNITY_Agent Rules & Settings|Agent Rules & Settings]]
- [[_COMMUNITY_App Initialization|App Initialization]]
- [[_COMMUNITY_ASGI Configuration|ASGI Configuration]]
- [[_COMMUNITY_Django Project Settings|Django Project Settings]]
- [[_COMMUNITY_Django URL Routing|Django URL Routing]]
- [[_COMMUNITY_WSGI Configuration|WSGI Configuration]]
- [[_COMMUNITY_Graphify Workflow & Rules|Graphify Workflow & Rules]]
- [[_COMMUNITY_Observability & DevSecOps Architecture|Observability & DevSecOps Architecture]]
- [[_COMMUNITY_Authentication & Zero-Trust Security|Authentication & Zero-Trust Security]]
- [[_COMMUNITY_Services Initialization|Services Initialization]]
- [[_COMMUNITY_Management Entrypoint|Management Entrypoint]]
- [[_COMMUNITY_Django Urlpatterns|Django Urlpatterns]]
- [[_COMMUNITY_ASGI Server Application|ASGI Server Application]]
- [[_COMMUNITY_WSGI Server Application|WSGI Server Application]]
- [[_COMMUNITY_Video Pipeline Specification|Video Pipeline Specification]]
- [[_COMMUNITY_Python Scaffolding with UV|Python Scaffolding with UV]]
- [[_COMMUNITY_Resilience & Fault Tolerance|Resilience & Fault Tolerance]]
- [[_COMMUNITY_DataLoader Pattern implementation|DataLoader Pattern implementation]]
- [[_COMMUNITY_API Versioning Strategies|API Versioning Strategies]]
- [[_COMMUNITY_Rate Limiting Patterns|Rate Limiting Patterns]]

## God Nodes (most connected - your core abstractions)
1. `run_text2img()` - 9 edges
2. `Settings` - 8 edges
3. `FluxClientError` - 8 edges
4. `start_text_to_image()` - 8 edges
5. `get_text_to_image_status()` - 8 edges
6. `text_to_image()` - 7 edges
7. `FastAPI App Instance` - 7 edges
8. `list_users()` - 6 edges
9. `TextToImageRequest` - 6 edges
10. `fetch_text_to_image_file()` - 6 edges

## Surprising Connections (you probably didn't know these)
- `TextToImageRequest` --semantically_similar_to--> `generate`  [INFERRED] [semantically similar]
  app/schemas.py → dgx_flux_text2image_server.py
- `FastAPI Proxy Architecture` --rationale_for--> `FastAPI App Instance`  [EXTRACTED]
  README_FASTAPI.md → app/main.py
- `normalize_style()` --semantically_similar_to--> `AD_STYLES`  [INFERRED] [semantically similar]
  app/schemas.py → dgx_flux_text2image_server.py
- `Flux AI Image Generation Integration` --conceptually_related_to--> `start_text_to_image()`  [EXTRACTED]
  admart_backend_spec.md → app/services/flux_client.py
- `FastAPI Proxy Architecture` --conceptually_related_to--> `FastAPI DGX1 Flux API App Instance`  [EXTRACTED]
  README_FASTAPI.md → dgx_flux_text2image_server.py

## Hyperedges (group relationships)
- **Flux Image Generation Proxy Flow** — app_main_text_to_image, services_flux_client_start_text_to_image, dgx_flux_text2image_server_generate, dgx_flux_text2image_server_run_text2img [INFERRED 0.85]
- **Django Application Bootstrap** — config_settings_django_settings, config_urls_urlpatterns, config_asgi_application, config_wsgi_application [EXTRACTED 1.00]
- **API Design and Implementation Template Flow** — api_design_principles_skill, resources_implementation_playbook, assets_rest_api_template [INFERRED 0.85]
- **Full Stack Orchestration Subagent Collaboration** — full_stack_orchestration_full_stack_feature_skill, backend_architect_skill, security_auditor_skill [EXTRACTED 1.00]

## Communities (28 total, 21 thin omitted)

### Community 0 - "Flux Client & Proxy Services"
Cohesion: 0.15
Nodes (19): Flux AI Image Generation Integration, Settings, _split_csv(), FastAPI DGX1 Flux API App Instance, generate, get_status, health, run_text2img (+11 more)

### Community 1 - "REST API Template Endpoint"
Cohesion: 0.17
Nodes (20): create_user(), delete_user(), ErrorDetail, ErrorResponse, get_user(), http_exception_handler(), list_users(), PaginatedResponse (+12 more)

### Community 2 - "Flux Image Generation Engine"
Cohesion: 0.2
Nodes (14): _build_prompt(), _clear_cuda_cache(), generate(), _generation_attempt_sizes(), get_t2i_pipe(), _gpu_max_memory(), _is_cuda_oom(), Admart DGX1 FLUX text-to-image API.  Copy this file to the DGX1 server that has (+6 more)

### Community 3 - "FastAPI App & Schemas"
Cohesion: 0.27
Nodes (12): FastAPI App Instance, health(), text_to_image(), text_to_image_alias(), text_to_image_file(), text_to_image_status(), normalize_style(), TextToImageJobResponse (+4 more)

### Community 4 - "API Design Principles & Best Practices"
Cohesion: 0.29
Nodes (7): API Design Principles Skill, API Design Checklist, REST API FastAPI Template, GraphQL Schema Design Reference, REST API Best Practices Reference, API Design Principles Implementation Playbook, Standardized Error Handling Response Schema

### Community 5 - "Agent Architectural Skills"
Cohesion: 0.5
Nodes (4): Backend Architect Skill, Full-Stack Orchestration Skill, Python Project Scaffolding Skill, Security Auditor Skill

## Knowledge Gaps
- **39 isolated node(s):** `Run administrative tasks.`, `Admart DGX1 FLUX text-to-image API.  Copy this file to the DGX1 server that has`, `Production-ready REST API template using FastAPI. Includes pagination, filtering`, `List users with pagination and filtering.`, `Partially update user.` (+34 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `start_text_to_image()` connect `Flux Client & Proxy Services` to `FastAPI App & Schemas`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Why does `run_text2img()` connect `Flux Image Generation Engine` to `FastAPI App & Schemas`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Why does `list_users()` connect `REST API Template Endpoint` to `FastAPI App & Schemas`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `str` (e.g. with `_is_cuda_oom()` and `run_text2img()`) actually correct?**
  _`str` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Run administrative tasks.`, `Admart DGX1 FLUX text-to-image API.  Copy this file to the DGX1 server that has`, `Production-ready REST API template using FastAPI. Includes pagination, filtering` to the rest of the system?**
  _39 weakly-connected nodes found - possible documentation gaps or missing edges._