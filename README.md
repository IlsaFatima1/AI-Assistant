# Havenly Project Audit & Architectural Analysis
**Prepared by:** Jules, Principal Software Engineer / Codebase Auditor
**Date:** July 2026
**Target Repository:** [IlsaFatima1/Havenly](https://github.com/IlsaFatima1/Havenly)

---

## 1. Executive Summary
**Havenly** is an advanced, highly specialized, production-ready real estate portal specifically engineered for the real estate landscape of **Karachi, Pakistan**. It represents an outstanding example of modern web engineering, beautifully integrating **React 19 (TypeScript)**, **Vite**, **Tailwind CSS v4.0.0**, and **Supabase (PostgreSQL)** into a high-performance, real-time application.

The project sets itself apart by avoiding generic boilerplate and implementing **domain-specific optimizations**:
1. **Locational Authority:** Restricts listings strictly to the bounds of Karachi with rigorous client-side and database-level geographical validation.
2. **Localized AI Search Engine:** Natively understands and translates local Pakistani real estate units (e.g., *lakh*, *crore*, *marla*) into standard quantitative metrics (PKR currency values and square footage) and precise search filters.
3. **Decoupled Real-time Messaging & Notification Pipeline:** Leverages advanced PostgreSQL triggers to coordinate real-time chat, in-app alerts, and asynchronous email notification outbox queuing entirely within the database.

This report provides a comprehensive, multi-layer architectural audit of the codebase, detailing its design choices, strengths, security posture, and a roadmap for future expansion.

---

## 2. System Architecture Diagram & Data Flow
The application follows a clean, feature-driven unidirectional architecture that ensures decoupling and strict separation of concerns.

```
       +--------------------------------------------------------+
       |                  User Browser (Client)                 |
       |  [React 19 + Vite] -- [Tailwind v4] -- [Framer Motion] |
       +--------------------------------------------------------+
              |                    ^                     |
         REST / Auth            Real-time                |
         HTTP Requests          (WebSockets)         AI Prompts
              |                    |                     |
              v                    v                     v
       +---------------+  +------------------+  +-----------------+
       | Supabase Auth |  | Supabase Realtime|  | Supabase Edge   |
       |  (JWT & RLS)  |  |   (PostgreSQL)   |  | Functions (AI)  |
       +---------------+  +------------------+  +-----------------+
              |                    ^                     |
              |                    |                     |
              +----------+---------+                     |
                         |                               |
                         v                               v
       +-------------------------------------+  +-----------------+
       |         PostgreSQL Database         |  |   External LLM  |
       | - Row Level Security (RLS)          |  |  (Gemini API /  |
       | - Area & Lat/Lng Constraints        |  |  openai-agents) |
       | - Real-time Messaging Triggers       |  +-----------------+
       | - Notification Outbox & Email Queue |
       +-------------------------------------+
```

---

## 3. Tech Stack Breakdown
* **Frontend Framework:** `React 19.2.0` — Utilizing the latest React features and optimizations.
* **Build System:** `Vite 7.3.1` — Equipped with Fast Refresh via `@vitejs/plugin-react` and compiled using `TypeScript ~5.9.3`.
* **Styling Engine:** `Tailwind CSS v4.2.1` — Utilizes the new high-performance, CSS-first `@tailwindcss/vite` engine for near-instant build times and optimized utility compilation.
* **Animation:** `Framer Motion v12.35.0` — Powering smooth micro-interactions, layout transitions, and page entry effects.
* **Database & BaaS:** `Supabase` — Integrated via `@supabase/supabase-js v2.109.0` for Authentication, PostgreSQL Database, Storage Buckets, Realtime WebSockets, and Edge Functions.
* **State Management:** Native `React Context` split cleanly across domains (`AuthProvider`, `PropertyProvider`, `MessagingProvider`, `NotificationProvider`, `ThemeProvider`).
* **Query Caching:** `@tanstack/react-query v5.101.2` — Used to orchestrate asynchronous data fetching, automatic retries, and cache synchronization.
* **Form & Schema Validation:** `React Hook Form v7.81.0` combined with `Zod v4.4.3` for strong client-side type inference and validation.

---

## 4. Deep-Dive: Database Schema, Security & Triggers

The relational schema in `supabase/migrations` is designed to be highly authoritative. Security and business validations are pushed directly into the PostgreSQL layer rather than relying solely on the client.

### A. The Karachi-Only Property Catalog (`properties` table)
Designed with strict check constraints to ensure the integrity of Karachi listings:
* **Coordinates Check:** `latitude between 24.45 and 25.55` and `longitude between 66.55 and 67.65` prevents global coordinates from polluting the map.
* **Geographical Area Whitelist:** The `area` column is validated via a `check` constraint whitelisting only authentic Karachi residential and commercial zones:
  ```sql
  area check(area in ('Bahadurabad','Buffer Zone','Clifton','Defence View','DHA',
                      'Federal B Area','Garden','Gulistan-e-Johar','Gulshan-e-Iqbal',
                      'Karsaz','Keamari','Korangi','Landhi','Liaquatabad','Malir',
                      'Nazimabad','North Karachi','North Nazimabad','PECHS',
                      'Saddar','Scheme 33','Shah Faisal Colony'))
  ```
* **Property Type & Purpose Whitelist:** Restricts properties to valid types (`house`, `apartment`, `villa`, `townhouse`, `land`, `commercial`) and intent (`sale`, `rent`).

### B. Row Level Security (RLS) Policies
Each table has explicit RLS policies to safeguard personal user data while allowing open public discoverability:
* **Properties Table:**
  * Select: Allowed if the property is `'published'`, or if the viewer is the `owner_id` or an admin (`public.is_admin()`).
  * Insert: Authenticated users can insert properties *only* if the `owner_id` matches their own authenticated ID (`owner_id = auth.uid()`) and the city is strictly `'Karachi'`.
* **Favorites Table:** Users can only view or manage their own favorites list. Insertion requires checking that the target property is actually in a `'published'` state:
  ```sql
  create policy "users add own favorites" on public.favorites
  for insert with check(user_id = auth.uid() and exists(
    select 1 from properties p where p.id = property_id and p.status = 'published'
  ));
  ```

### C. Automated Messaging & Notification Triggers
The database actively drives the application state, taking the performance burden off client browsers.
* **Durable Notification Fan-out:** When a new row is added to the `messages` table, the database automatically invokes the `notify_conversation_message` trigger:
  ```sql
  create trigger notify_conversation_message
  after insert on public.messages
  for each row execute function public.notify_conversation_message();
  ```
  This automatically inserts an unread notification into the `notifications` table for every other member of the conversation. If a recipient is offline, the notification is durably saved in their inbox feed.
* **Decoupled Email Outbox:** Whenever a notification is created, the trigger `queue_notification_email` checks the user's `notification_preferences`. If email delivery is enabled, it queues a pending record in the `notification_email_outbox` table. This allows the backend to handle reliable asynchronous email dispatch without blocking database transactions.

---

## 5. Karachi-Specific Domain Validation
One of Havenly's strongest design details is the unified synchronization of client-side validation (`Zod` schema in the frontend) with server-side limits (`PostgreSQL` table checks):

```typescript
// src/features/properties/schema.ts
export const propertySchema = z.object({
  ...
  city: z.literal(KARACHI_CITY),
  area: z.enum(KARACHI_AREAS, { error: 'Select a valid Karachi area.' }),
  latitude: z.coerce.number().min(-90).max(90),
  longitude: z.coerce.number().min(-180).max(180),
}).refine((data) => isInKarachi(data.latitude, data.longitude), {
  message: 'The exact pin must be within Karachi.',
  path: ['latitude']
})
```

The `isInKarachi` helper checks the exact bounds matching the SQL layer perfectly:
```typescript
// src/lib/karachi.ts
export const KARACHI_BOUNDS = { north: 25.55, south: 24.45, east: 67.65, west: 66.55 }
export function isInKarachi(lat: number, lng: number) {
  return lat >= KARACHI_BOUNDS.south && lat <= KARACHI_BOUNDS.north &&
         lng >= KARACHI_BOUNDS.west && lng <= KARACHI_BOUNDS.east
}
```
This guarantees zero data mismatch between the user interface and the persistent database layer.

---

## 6. AI Engine & Conversational Search Integration
Havenly features a custom `aiService` that bridges natural language queries with the properties database.

### Local Unit Translation
In Pakistan, properties are bought/sold in terms of local pricing units:
* **1 Lakh** = 100,000 PKR
* **1 Crore** = 10,000,000 PKR
And size is measured in:
* **1 Marla** = ~225 Square Feet

Havenly's AI parser (`src/features/ai/ai-service.ts`) includes robust regular expressions to capture these terms natively and translate them into SQL-friendly filters:
```typescript
const crore = q.match(/(?:under|below|max|upto|up to)?\s*(\d+(?:\.\d+)?)\s*crore/);
const lakh = q.match(/(?:under|below|max|upto|up to)?\s*(\d+(?:\.\d+)?)\s*lakh/);
const marla = q.match(/(\d+(?:\.\d+)?)\s*marla/);

if (crore) filters.maxPrice = String(Number(crore[1]) * 10_000_000);
if (lakh) filters.maxPrice = String(Number(lakh[1]) * 100_000);
if (marla && !filters.minSquareFeet && !filters.maxSquareFeet) {
  const feet = Number(marla[1]) * 225;
  filters.minSquareFeet = String(Math.round(feet * 0.9));
  filters.maxSquareFeet = String(Math.round(feet * 1.1));
}
```
This enables incredible search behaviors. An input query like:
> *"I need a 5 Marla house in DHA under 2 Crore"*

is dynamically transformed into:
* **Area:** `DHA`
* **Purpose:** `sale`
* **Property Type:** `house`
* **Max Price:** `20,000,000 PKR`
* **Square Footage range:** `1,013 - 1,238 sq. ft.` (approx. 5 Marlas)

This sets Havenly far ahead of typical property portals that require users to manually adjust dozens of dropdowns.

---

## 7. Major Architectural Strengths & Best Practices

1. **Edge Function Resiliency with Local Fallbacks:**
   The `aiService` is designed to attempt calling the Supabase Edge Function `ai-property`. However, if the network is offline or the Edge Function is not yet configured, it seamlessly falls back to local regex-based parsing and chat behaviors. The user experience remains uninterrupted.
2. **Database Rate Limiting & Quotas:**
   The `consume_ai_quota` SQL function tracks AI usage per user on a rolling 1-minute window, restricting requests to 20 per minute. This rate-limiting is extremely robust as it operates inside the database transactions.
3. **Optimistic & Real-time State Updates:**
   The `PropertyProvider` sets up a Supabase Realtime channel listening to PostgreSQL changes. When any listing is added, updated, or removed, the local UI automatically refetches, sorts, and re-renders in real-time.
4. **Structured Global Error & Event Monitoring:**
   Features a custom telemetry and error-tracking engine (`src/lib/monitoring.ts`) that listens to unhandled window promises and errors. If Sentry is installed on the window, it automatically forwards structured debug payloads for real-time app observability.

---

## 8. Areas of Improvement & Suggested Mitigations

While Havenly is engineered beautifully, the following architectural additions would elevate it to absolute world-class standard:

| Feature / Area | Observation | Recommendation / Mitigation |
| :--- | :--- | :--- |
| **Database Indices** | Extensive indices are present for common fields (`area`, `purpose`, `property_type`, `price`), but free-text query parsing is run using string-matching. | Implement PostgreSQL **Full-Text Search (FTS)** or GIN/Trigram indexes on `title` and `description` in the database to support fast partial-word queries. |
| **Real-time Map Clustering** | If Karachi has thousands of listings, rendering them all as separate map pins can cause browser rendering lags. | Introduce **marker clustering** or grid-based heatmaps inside the `GoogleMapPicker` component when displaying crowded zones like DHA or Clifton. |
| **Media Optimization** | Properties support up to 12 image URLs, but they are stored as plain text. | Implement an automated **image pipeline** using Supabase storage transformation options (e.g., resizing to 800px width with webp compression) to keep image payloads tiny and fast. |
| **Offline Synchronization** | If a user is on the go (which is highly likely in mobile real estate hunts), network drops can cause issues. | Introduce a service worker with **offline caching** for previously loaded listings, enabling buyers to view their favorite properties even without active mobile data. |

---

## 9. Future Roadmap for Havenly

* **Phase 1: Full-Text Search Migration:** Migrate `prisma/search-indexes.sql` into active Supabase migrations to enable native Postgres Trigram fuzzy searching.
* **Phase 2: Verified Seller Badge:** Introduce KYC verification tables for real-estate agents, displaying a blue tick badge on verified owner cards to combat marketplace spam.
* **Phase 3: Interactive Floorplan Viewer:** Build support for interactive 3D floorplans or panoramic 360-degree virtual property tours within the listing pages.
* **Phase 4: Automated WhatsApp API Hook:** Enable agents to toggle "Lead Forwarding," which automatically posts chat notifications directly to their registered Pakistani WhatsApp numbers.

---
### Final Audit Score: **9.8 / 10** (Exceptional Engineering)
The repository represents an outstanding, production-ready implementation of real-world verticalized SaaS. Its database triggers, security layer, localized AI capability, and unified client-server validation make it a stellar benchmark for modern application architecture.
