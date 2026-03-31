-- ================================================================
-- Phase 2.1: Demo API Keys for the landing page
-- 10 pre-generated keys assigned randomly per browser session
-- Raw keys: interlude-demo-001 through interlude-demo-010
-- Tier 'demo': 50 req/hr, export limited to 100 rows, 10 exports max
-- ================================================================

INSERT INTO api_users (email, org_name, tier, api_key_hash, rate_limit_per_hour)
VALUES
  ('demo-001@interlude.demo', 'Demo User 1', 'demo', '2616ec7e1fcac8a39bae2caddc3c5df3c658b8e0d88bb53c064c68f04a01d658', 50),
  ('demo-002@interlude.demo', 'Demo User 2', 'demo', '02c9d15dfec0d3cc1a5f90bc20fe049f28be0551b41bc446762c9806837af90f', 50),
  ('demo-003@interlude.demo', 'Demo User 3', 'demo', '6de9deff7a2f379a2a5cf7758e763f22852b9a78543d374f6cb9c5787fb876cc', 50),
  ('demo-004@interlude.demo', 'Demo User 4', 'demo', '02667a5a8eea102f1be500bbb3322ac0878c6cc397b9e834ad7d62c3e5b828a7', 50),
  ('demo-005@interlude.demo', 'Demo User 5', 'demo', 'ac61c8d79bbfb226fdd63c94ac1afecac6629dd5c24ee21de30c8f42f8526235', 50),
  ('demo-006@interlude.demo', 'Demo User 6', 'demo', '3599c92d83efe4e38f583b0f7997a096b37f616a76ad8f0c80c1e4a8b93a32e4', 50),
  ('demo-007@interlude.demo', 'Demo User 7', 'demo', '39d495535d51cca523ca0fda7db13459a5b85446e87bb7fdb7dbebc1b15fc174', 50),
  ('demo-008@interlude.demo', 'Demo User 8', 'demo', '2d87dd2ec4c00cf86b479943adb9a6a6496d0823492cd8f7db4ad0e9ffdaa3e7', 50),
  ('demo-009@interlude.demo', 'Demo User 9', 'demo', 'a1443a3df85f8e55bd81a49ebd2ce1ea330f5a5845043e9b637d6637109f7c4a', 50),
  ('demo-010@interlude.demo', 'Demo User 10', 'demo', '2d80fa6bb2b1af8f58b3c7165a637ba417634a46c7fb5973b07e30beb8c7d4d1', 50)
ON CONFLICT (email) DO NOTHING;
