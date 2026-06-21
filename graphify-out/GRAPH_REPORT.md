# Graph Report - admart-backend  (2026-06-20)

## Corpus Check
- 30 files · ~22,234 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 686 nodes · 776 edges · 86 communities (51 shown, 35 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 85 edges (avg confidence: 0.6)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `44a95523`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

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
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]

## God Nodes (most connected - your core abstractions)
1. `2.2 Route Map & Page Details` - 20 edges
2. `Admart (Vidify) — Complete Backend Agent Specification` - 19 edges
3. `Capabilities` - 18 edges
4. `UserAuthTests` - 16 edges
5. `8. Complete API Endpoint Reference` - 16 edges
6. `Pre-Implementation Review` - 15 edges
7. `REST API Best Practices` - 15 edges
8. `GraphQL Schema Design Patterns` - 13 edges
9. `RegisterView` - 12 edges
10. `CustomTokenObtainPairView` - 12 edges

## Surprising Connections (you probably didn't know these)
- `normalize_style()` --semantically_similar_to--> `AD_STYLES`  [INFERRED] [semantically similar]
  app/schemas.py → dgx_flux_text2image_server.py
- `TextToImageRequest` --semantically_similar_to--> `generate`  [INFERRED] [semantically similar]
  app/schemas.py → dgx_flux_text2image_server.py
- `Flux AI Image Generation Integration` --conceptually_related_to--> `start_text_to_image()`  [EXTRACTED]
  admart_backend_spec.md → app/services/flux_client.py
- `FastAPI Proxy Architecture` --rationale_for--> `FastAPI App Instance`  [EXTRACTED]
  README_FASTAPI.md → app/main.py
- `FastAPI Proxy Architecture` --conceptually_related_to--> `FastAPI DGX1 Flux API App Instance`  [EXTRACTED]
  README_FASTAPI.md → dgx_flux_text2image_server.py

## Hyperedges (group relationships)
- **Flux Image Generation Proxy Flow** — app_main_text_to_image, services_flux_client_start_text_to_image, dgx_flux_text2image_server_generate, dgx_flux_text2image_server_run_text2img [INFERRED 0.85]
- **Django Application Bootstrap** — config_settings_django_settings, config_urls_urlpatterns, config_asgi_application, config_wsgi_application [EXTRACTED 1.00]
- **API Design and Implementation Template Flow** — api_design_principles_skill, resources_implementation_playbook, assets_rest_api_template [INFERRED 0.85]
- **Full Stack Orchestration Subagent Collaboration** — full_stack_orchestration_full_stack_feature_skill, backend_architect_skill, security_auditor_skill [EXTRACTED 1.00]

## Communities (86 total, 35 thin omitted)

### Community 0 - "Flux Client & Proxy Services"
Cohesion: 0.11
Nodes (31): Flux AI Image Generation Integration, Settings, _split_csv(), FastAPI App Instance, health(), text_to_image(), text_to_image_alias(), text_to_image_file() (+23 more)

### Community 1 - "REST API Template Endpoint"
Cohesion: 0.17
Nodes (20): create_user(), delete_user(), ErrorDetail, ErrorResponse, get_user(), http_exception_handler(), list_users(), PaginatedResponse (+12 more)

### Community 2 - "Flux Image Generation Engine"
Cohesion: 0.2
Nodes (14): _build_prompt(), _clear_cuda_cache(), generate(), _generation_attempt_sizes(), get_t2i_pipe(), _gpu_max_memory(), _is_cuda_oom(), Admart DGX1 FLUX text-to-image API.  Copy this file to the DGX1 server that has (+6 more)

### Community 3 - "FastAPI App & Schemas"
Cohesion: 0.13
Nodes (14): 11. File Storage, 12. Environment Variables, 13. CORS Configuration, 14. Error Response Format, 15. Database Schema (PostgreSQL), 17. Key Implementation Notes, 18. Development Order (Suggested), 1. Project Overview (+6 more)

### Community 4 - "API Design Principles & Best Practices"
Cohesion: 0.29
Nodes (7): API Design Principles Skill, API Design Checklist, REST API FastAPI Template, GraphQL Schema Design Reference, REST API Best Practices Reference, API Design Principles Implementation Playbook, Standardized Error Handling Response Schema

### Community 5 - "Agent Architectural Skills"
Cohesion: 0.5
Nodes (4): Backend Architect Skill, Full-Stack Orchestration Skill, Python Project Scaffolding Skill, Security Auditor Skill

### Community 27 - "Rate Limiting Patterns"
Cohesion: 0.4
Nodes (5): code:block15 (X-RateLimit-Limit: 1000), code:python (from fastapi import HTTPException, Request), Headers, Implementation Pattern, Rate Limiting

### Community 28 - "Community 28"
Cohesion: 0.06
Nodes (31): 8.10 Social Accounts, 8.11 Publishing Schedule, 8.12 Analytics, 8.13 Brand Kit, 8.14 Billing, 8.15 Notifications, 8.1 Auth, 8.2 Users (+23 more)

### Community 29 - "Community 29"
Cohesion: 0.06
Nodes (30): API Contract & Documentation, API Design & Patterns, API Gateway & Load Balancing, Asynchronous Processing, Authentication & Authorization, Behavioral Traits, Caching Strategies, Capabilities (+22 more)

### Community 30 - "Community 30"
Cohesion: 0.07
Nodes (29): 1. RESTful Design Principles, 2. GraphQL Design Principles, 3. API Versioning Strategies, API Design Principles Implementation Playbook, Best Practices, code:block1 (/api/v1/users), code:python (from aiodataloader import DataLoader), code:block2 (Accept: application/vnd.api+json; version=1) (+21 more)

### Community 31 - "Community 31"
Cohesion: 0.07
Nodes (26): 1. Analyze Project Type, 2. Initialize Project with uv, 3. Generate FastAPI Project Structure, 4. Generate Django Project Structure, 5. Generate Python Library Structure, 6. Generate CLI Tool Structure, 7. Configure Development Tools, code:bash (# Create new project with uv) (+18 more)

### Community 32 - "Community 32"
Cohesion: 0.09
Nodes (23): 2.1 Application Shell, 2.2 Route Map & Page Details, 2. Complete Frontend Anatomy, `/analytics` — AnalyticsPage, `/auth` — AuthPage, `/billing` — BillingPage, `/brand-kit` — BrandKitPage, `/calendar` — CalendarPage (+15 more)

### Community 33 - "Community 33"
Cohesion: 0.09
Nodes (22): API Design Checklist, Authentication & Authorization, Documentation, Documentation, Error Handling, Filtering & Sorting, GraphQL-Specific Checks, HTTP Methods (+14 more)

### Community 34 - "Community 34"
Cohesion: 0.09
Nodes (22): 10. Infrastructure & CI/CD Setup, 11. Observability & Monitoring, 12. Performance Optimization, 1. Database Architecture Design, 2. Backend Service Architecture, 3. Frontend Component Architecture, 4. Backend Service Implementation, 5. Frontend Implementation (+14 more)

### Community 35 - "Community 35"
Cohesion: 0.09
Nodes (21): Application Security Testing, Behavioral Traits, Capabilities, Cloud Security, Compliance & Governance, DevSecOps & Security Automation, Do not use this skill when, Emerging Security Technologies (+13 more)

### Community 36 - "Community 36"
Cohesion: 0.13
Nodes (15): 3.1 User, 3.2 Video, 3.3 GeneratedImage, 3.4 Job, 3.5 SocialAccount, 3.6 AnalyticsRecord, 3.7 Plan/Credit Tiers, 3. Data Models (+7 more)

### Community 37 - "Community 37"
Cohesion: 0.14
Nodes (13): Agent Behavior & Guardrails, Agent Skills (invoke when the task matches), AGENTS.md — Backend (Django + DRF), API Documentation (Swagger / OpenAPI) — required for every endpoint, Code Documentation, Code Quality, Commands, Database & Migrations (safety) (+5 more)

### Community 38 - "Community 38"
Cohesion: 0.14
Nodes (13): Batch Endpoints, Bulk Operations, code:python (POST /api/users/batch), code:block22 (POST /api/orders), code:python (from fastapi.middleware.cors import CORSMiddleware), code:python (from fastapi import FastAPI), code:python (@app.get("/health")), CORS Configuration (+5 more)

### Community 39 - "Community 39"
Cohesion: 0.15
Nodes (13): 5.1 Overview, 5.2 API Flow, 5.3 Flux API Call (via Replicate), 5.4 Status Polling, 5.5 All Image Generation Endpoints, 5.6 SDXL Fallback, 5.7 Credit Deduction Rules, 5. ⭐ Flux AI Image Generation — Critical Feature (+5 more)

### Community 40 - "Community 40"
Cohesion: 0.15
Nodes (12): 1. Run the DGX1 Flux API, 2. Run the local FastAPI proxy, 3. Frontend environment, Admart FastAPI Text-to-Image Backend, code:bash (pip install fastapi uvicorn diffusers transformers accelerat), code:bash (curl http://100.104.174.12:8001/health), code:powershell (python -m venv .venv), code:powershell (curl http://127.0.0.1:8000/health) (+4 more)

### Community 41 - "Community 41"
Cohesion: 0.18
Nodes (11): code:block3 (GET /api/users              → 200 OK (with list)), code:block4 (POST /api/users), code:block5 (PUT /api/users/{id}), code:block6 (PATCH /api/users/{id}), code:block7 (DELETE /api/users/{id}), DELETE - Remove Resources, GET - Retrieve Resources, HTTP Methods and Status Codes (+3 more)

### Community 42 - "Community 42"
Cohesion: 0.22
Nodes (9): 1. Non-Null Types, 2. Interfaces for Polymorphism, 3. Unions for Heterogeneous Results, 4. Input Types, code:graphql (type User {), code:graphql (interface Node {), code:graphql (union SearchResult = User | Post | Comment), code:graphql (input CreateUserInput {) (+1 more)

### Community 43 - "Community 43"
Cohesion: 0.2
Nodes (9): Best Practices Summary, code:graphql (# user.graphql), code:graphql (type Subscription {), code:graphql (scalar DateTime), Custom Scalars, GraphQL Schema Design Patterns, Modular Schema Structure, Schema Organization (+1 more)

### Community 44 - "Community 44"
Cohesion: 0.29
Nodes (7): 1. Input/Payload Pattern, 2. Optimistic Response Support, 3. Batch Mutations, code:graphql (input BatchCreateUserInput {), code:graphql (input CreatePostInput {), code:graphql (type UpdateUserPayload {), Mutation Design Patterns

### Community 45 - "Community 45"
Cohesion: 0.29
Nodes (7): code:python (from aiodataloader import DataLoader), code:python (from graphql import GraphQLError), code:python (def complexity_limit_validator(max_complexity: int):), DataLoader Pattern, N+1 Query Problem Solutions, Query Complexity Analysis, Query Depth Limiting

### Community 46 - "Community 46"
Cohesion: 0.29
Nodes (7): code:python (GET /api/users?limit=20&cursor=eyJpZCI6MTIzfQ), code:block11 (GET /api/users?page=2), code:python (GET /api/users?page=2&page_size=20), Cursor-Based Pagination (for large datasets), Link Header Pagination (RESTful), Offset-Based Pagination, Pagination Patterns

### Community 47 - "Community 47"
Cohesion: 0.29
Nodes (7): code:block12 (/api/v1/users), code:block13 (GET /api/users), code:block14 (GET /api/users?version=2), Header Versioning, Query Parameter, URL Versioning (Recommended), Versioning Strategies

### Community 48 - "Community 48"
Cohesion: 0.33
Nodes (5): API Design Principles, Do not use this skill when, Instructions, Resources, Use this skill when

### Community 49 - "Community 49"
Cohesion: 0.4
Nodes (5): Arguments and Filtering, code:graphql (type Query {), code:graphql (type User {), Computed Fields, Field Design

### Community 50 - "Community 50"
Cohesion: 0.4
Nodes (5): Built-in Directives, code:graphql (type User {), code:graphql (directive @auth(requires: Role = USER) on FIELD_DEFINITION), Custom Directives, Directives

### Community 51 - "Community 51"
Cohesion: 0.4
Nodes (5): code:graphql (type User {), code:graphql (type CreateUserPayload {), Error Handling, Errors in Payload, Union Error Pattern

### Community 52 - "Community 52"
Cohesion: 0.4
Nodes (5): code:graphql (type User {), code:graphql (# v1 - Initial), Field Deprecation, Schema Evolution, Schema Versioning

### Community 53 - "Community 53"
Cohesion: 0.4
Nodes (5): code:graphql (type UserConnection {), code:graphql (type UserList {), Offset Pagination (Simpler), Pagination Patterns, Relay Cursor Pagination (Recommended)

### Community 54 - "Community 54"
Cohesion: 0.4
Nodes (5): API Keys, Authentication and Authorization, Bearer Token, code:block17 (Authorization: Bearer eyJhbGciOiJIUzI1NiIs...), code:block18 (X-API-Key: your-api-key-here)

### Community 55 - "Community 55"
Cohesion: 0.4
Nodes (5): code:block1 (# Good - Plural nouns), code:block2 (# Shallow nesting (preferred)), Nested Resources, Resource Naming, URL Structure

### Community 56 - "Community 56"
Cohesion: 0.5
Nodes (4): code:json ({), Consistent Structure, Error Response Format, Status Code Guidelines

### Community 57 - "Community 57"
Cohesion: 0.08
Nodes (47): APIView, TokenObtainPairSerializer, TokenObtainPairView, AuthResponseSerializer, CustomTokenObtainPairSerializer, ForgotPasswordSerializer, GoogleAuthSerializer, MessageSerializer (+39 more)

### Community 58 - "Community 58"
Cohesion: 0.07
Nodes (16): APITestCase, Test forgot password request responds with success regardless of user existence., Test resetting password with a valid signed token., Test resetting password with an invalid token fails., Test suite for User Authentication and registration endpoints., Test mock Google OAuth exchange creates user and returns JWT tokens., Test logout returns standard success message., Set up test user data. (+8 more)

### Community 59 - "Community 59"
Cohesion: 0.12
Nodes (13): AbstractBaseUser, BaseUserAdmin, BaseUserManager, PermissionsMixin, Custom UserAdmin class to support our custom User model in Django Admin., UserAdmin, Meta, Create and save a regular User with the given email and password. (+5 more)

### Community 63 - "Community 63"
Cohesion: 0.29
Nodes (7): 7.1 Platform APIs, 7.2 Publish Endpoint, 7.3 OAuth Flows, 7. Publishing Pipeline, code:block16 (TikTok:    TikTok for Developers - Content Posting API v2), code:block17 (POST /videos/:id/publish), code:block18 (GET  /social/connect/tiktok      → redirect to TikTok OAuth)

### Community 64 - "Community 64"
Cohesion: 0.4
Nodes (5): 10. Real-time Communication, code:block35 (GET /jobs/:jobId/stream), code:block36 (ws://api/ws), Option A: Server-Sent Events (SSE) — Recommended, Option B: WebSocket

### Community 75 - "Community 75"
Cohesion: 0.4
Nodes (5): 6.1 Models & Credit Costs, 6.2 Video Generation Flow, 6.3 Job Status Stages, 6. Video Generation Pipeline, code:block15 (POST /videos/generate)

### Community 76 - "Community 76"
Cohesion: 0.4
Nodes (5): 9.1 Credit Costs Summary, 9.2 Credit Operations, 9.3 Credit Reset, 9. Credits System, code:block34 (POST /credits/deduct      — internal, called by generation s)

### Community 77 - "Community 77"
Cohesion: 0.5
Nodes (4): 4.1 Strategy, 4.2 Endpoints, 4. Authentication & Authorization, code:block9 (POST   /auth/register          — email + password signup, cr)

### Community 78 - "Community 78"
Cohesion: 0.67
Nodes (3): 16. Recommended Tech Stack, Option A — Node.js (Express/Fastify), Option B — Python (FastAPI)

### Community 79 - "Community 79"
Cohesion: 0.67
Nodes (3): Cache Headers, Caching, code:block20 (# Client caching)

### Community 80 - "Community 80"
Cohesion: 0.67
Nodes (3): code:block8 (# Filtering), Filtering, Sorting, and Searching, Query Parameters

## Knowledge Gaps
- **364 isolated node(s):** `Run administrative tasks.`, `Production-ready REST API template using FastAPI. Includes pagination, filtering`, `List users with pagination and filtering.`, `Partially update user.`, `URL configuration for config project.  The `urlpatterns` list routes URLs to vie` (+359 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **35 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Admart (Vidify) — Complete Backend Agent Specification` connect `FastAPI App & Schemas` to `Community 32`, `Community 64`, `Community 36`, `Community 39`, `Community 75`, `Community 76`, `Community 77`, `Community 78`, `Community 28`, `Community 63`?**
  _High betweenness centrality (0.029) - this node is a cross-community bridge._
- **Why does `post()` connect `Community 57` to `Flux Client & Proxy Services`?**
  _High betweenness centrality (0.025) - this node is a cross-community bridge._
- **What connects `Run administrative tasks.`, `Production-ready REST API template using FastAPI. Includes pagination, filtering`, `List users with pagination and filtering.` to the rest of the system?**
  _364 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Flux Client & Proxy Services` be split into smaller, more focused modules?**
  _Cohesion score 0.11 - nodes in this community are weakly interconnected._
- **Should `FastAPI App & Schemas` be split into smaller, more focused modules?**
  _Cohesion score 0.13 - nodes in this community are weakly interconnected._
- **Should `Community 28` be split into smaller, more focused modules?**
  _Cohesion score 0.06 - nodes in this community are weakly interconnected._
- **Should `Community 29` be split into smaller, more focused modules?**
  _Cohesion score 0.06 - nodes in this community are weakly interconnected._