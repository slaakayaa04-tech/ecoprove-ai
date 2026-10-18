// scripts/deploy.js
// Kullanım:
//   npx hardhat run scripts/deploy.js                      (yerel deneme, ücretsiz)
//   npx hardhat run scripts/deploy.js --network sepolia    (gerçek test ağı)
const hre = require("hardhat");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log("Yayınlayan hesap:", deployer.address);

  const Registry = await hre.ethers.getContractFactory("EcoProveRegistry");
  const registry = await Registry.deploy();
  await registry.waitForDeployment();

  console.log("EcoProveRegistry adresi:", await registry.getAddress());
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
