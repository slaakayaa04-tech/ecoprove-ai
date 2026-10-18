// test/registry.test.js
const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("EcoProveRegistry", function () {
  let registry, owner, other, leafA, leafB, root;
  const CITY = "Ankara";
  const PERIOD = "2020-01";

  beforeEach(async function () {
    [owner, other] = await ethers.getSigners();
    const Registry = await ethers.getContractFactory("EcoProveRegistry");
    registry = await Registry.deploy();
    await registry.waitForDeployment();

    // İki kayıtlı küçük bir Merkle ağacı
    leafA = ethers.keccak256(ethers.toUtf8Bytes("kayit-A"));
    leafB = ethers.keccak256(ethers.toUtf8Bytes("kayit-B"));
    const [lo, hi] =
      leafA.toLowerCase() <= leafB.toLowerCase() ? [leafA, leafB] : [leafB, leafA];
    root = ethers.keccak256(ethers.concat([lo, hi]));
  });

  it("kökü saklar ve geri okur", async function () {
    await registry.storeRoot(CITY, PERIOD, root, 2);
    const [r, count, ts] = await registry.getRoot(CITY, PERIOD);
    expect(r).to.equal(root);
    expect(count).to.equal(2);
    expect(ts).to.be.gt(0);
  });

  it("doğru kaydı kanıtla doğrular", async function () {
    await registry.storeRoot(CITY, PERIOD, root, 2);
    expect(await registry.verify(CITY, PERIOD, leafA, [leafB])).to.equal(true);
    expect(await registry.verify(CITY, PERIOD, leafB, [leafA])).to.equal(true);
  });

  it("değiştirilmiş kaydı reddeder", async function () {
    await registry.storeRoot(CITY, PERIOD, root, 2);
    const tampered = ethers.keccak256(ethers.toUtf8Bytes("kayit-A-degistirildi"));
    expect(await registry.verify(CITY, PERIOD, tampered, [leafB])).to.equal(false);
  });

  it("aynı şehir ve ayı ikinci kez yazdırmaz", async function () {
    await registry.storeRoot(CITY, PERIOD, root, 2);
    await expect(registry.storeRoot(CITY, PERIOD, root, 2)).to.be.revertedWith(
      "already stored"
    );
  });

  it("sadece sahibi kök yazabilir", async function () {
    await expect(
      registry.connect(other).storeRoot(CITY, PERIOD, root, 2)
    ).to.be.revertedWith("only owner");
  });

  it("olmayan kaydı okurken hata verir", async function () {
    await expect(registry.getRoot(CITY, "1999-01")).to.be.revertedWith("not found");
  });
});
