# Security Specification — SMC Remote Bridge

## 1. Data Invariants
1. A bridge room (`/rooms/{roomId}`) MUST have a cryptographic pairing ID (`^[a-zA-Z0-9_-]{12,64}$`). Listing `/rooms` or `/rooms/{roomId}/items` is strictly forbidden (`allow list: if false`) so unauthenticated enumeration is impossible.
2. Every room item (`/rooms/{roomId}/items/{itemId}`) MUST have `itemId` in `['data', 'file', 'answer', 'prompt', 'lists', 'cmd', 'resp']`, matching `kind == itemId`, and bounded payload sizes (`text <= 750000` bytes).
3. User profiles (`/users/{userId}`) and saved pairing shortcuts (`/users/{userId}/savedRooms/{roomId}`) MUST require verified Google Sign-In (`request.auth != null && request.auth.uid == userId && request.auth.token.email_verified == true`).
4. No shadow/unknown fields are allowed (`keys().hasOnly(...)` enforced on every entity).

## 2. Dirty Dozen Payloads (Must Return PERMISSION_DENIED)
1. `LIST /rooms` -> Denied (`allow list: if false`).
2. `GET /rooms/abc` (short 3-char room ID) -> Denied (`isValidRoomId` requires length >= 12).
3. `CREATE /rooms/validroom1234` with missing `symbol` -> Denied (`keys().hasAll`).
4. `CREATE /rooms/validroom1234` with extra shadow field `isAdmin: true` -> Denied (`keys().hasOnly`).
5. `UPDATE /rooms/validroom1234` with `name` > 120 chars -> Denied (`.size() <= 120`).
6. `CREATE /rooms/validroom1234/items/unknown` -> Denied (`itemId` allowlist).
7. `CREATE /rooms/validroom1234/items/cmd` with `kind: 'file'` (kind mismatch) -> Denied (`data.kind == itemId`).
8. `CREATE /rooms/validroom1234/items/file` with `text` > 750000 chars -> Denied.
9. `GET /users/otherUid` while signed in as `userA` -> Denied (`isOwner`).
10. `CREATE /users/userA` with `email_verified == false` -> Denied (`emailVerified()`).
11. `CREATE /users/userA/savedRooms/validroom1234` with `ownerId: 'userB'` -> Denied (`ownerId == userId`).
12. `DELETE /rooms/validroom1234` -> Denied (`allow delete: if false`).
