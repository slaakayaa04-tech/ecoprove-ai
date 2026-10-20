# 🛡️ Security, Data Integrity & Honest Boundaries

## 1. Cryptographic Integrity Scheme

Every scored climate record is deterministically serialized and hashed using **keccak256**:

```text
leaf = keccak256("date|source|tmean|score|status")
```

Records are sorted by `(date, source)` and grouped by month (`YYYY-MM`). Pairs of leaves are combined using **sorted-pair hashing** (`min(a, b) || max(a, b)`), matching the OpenZeppelin / `EcoProveRegistry.sol` verification logic. If a layer has an odd number of nodes, the last node is promoted to the next layer.

### Why This Prevents Tampering
- Changing even a single digit of `tmean` (e.g., `2.1` → `2.2`), `score`, or `status` produces a completely different 256-bit leaf hash.
- When combined with the Merkle proof, the resulting root will not match the root stored in `EcoProveRegistry`, causing `verify()` to return `false`.

---

## 2. Smart Contract Security (`EcoProveRegistry.sol`)

Deployed on Ethereum Sepolia at [`0x2b27fd49fd0C8325f8FE389a49BDDde1d6feCF89`](https://sepolia.etherscan.io/address/0x2b27fd49fd0C8325f8FE389a49BDDde1d6feCF89):

1. **Write-Once Immutability (`already stored`):**
   - `require(entries[key].timestamp == 0, "already stored");`
   - Once a root is stored for a `(city, period)` pair, it cannot be modified or deleted by anyone, including the contract owner.
2. **Owner-Only Sealing (`only owner`):**
   - `require(msg.sender == owner, "only owner");`
   - Unauthorized wallets cannot inject fake monthly roots.
3. **Zero-Trust Public Verification:**
   - The `verify()` function is `external view`, meaning auditors and end users can verify records directly against Ethereum Sepolia without connecting a wallet, holding tokens, or trusting our web server.
4. **Automated Unit Tests (`test/registry.test.js`):**
   - 6 Hardhat tests cover storing/reading roots, valid Merkle proof verification, tampered record rejection, duplicate write prevention (`already stored`), unauthorized sender rejection (`only owner`), and missing entry handling (`not found`).

---

## 3. Key Management & Operational Safety

- The publisher private key is stored exclusively in a local `.env` file and listed in `.gitignore`.
- The public Streamlit web application performs **read-only RPC calls** (`getRoot` and `verify`) and requires **no secrets or private keys**.
- Dedicated Sepolia testnet wallet (`0x471F4ac021b9a4E72626fbd51C6119459052b494`) holds only test ETH.

---

## 4. Honest System Boundaries

To ensure scientific and technical transparency, we explicitly state what EcoProve AI **does** and **does not** claim:

1. **Integrity vs. Physical Accuracy:** Blockchain sealing proves that a record **was not changed after it was sealed**. It does not prove that a physical sensor was calibrated correctly.
2. **Off-Chain Scoring vs. On-Chain Sealing:** Multi-source cross-checking and statistical anomaly detection happen off-chain in Python; the smart contract seals the output and verifies membership proofs.
3. **Partial Source Overlap:** Reanalysis products (ERA5, MERRA-2) assimilate station and satellite observations, so the three sources are not completely independent.
4. **Geographic & Temporal Scope:** Current prototype evaluates daily records for Ankara, Türkiye on the Ethereum Sepolia testnet. Scaling to additional cities requires only 1 transaction per city per month.
