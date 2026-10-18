// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title EcoProve Registry
/// @notice Her şehir ve ay için veri kayıtlarının Merkle kökünü saklar,
///         tek bir kaydın o kökün parçası olduğunu doğrular.
contract EcoProveRegistry {
    struct Entry {
        bytes32 root;
        uint32 count;
        uint64 timestamp;
    }

    address public owner;
    mapping(bytes32 => Entry) private entries;

    event RootStored(string city, string period, bytes32 root, uint32 count, uint64 timestamp);

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "only owner");
        _;
    }

    function _key(string memory city, string memory period) private pure returns (bytes32) {
        return keccak256(abi.encodePacked(city, "|", period));
    }

    /// @notice Bir şehir ve ay için kökü kaydeder. Aynı ay iki kez yazılamaz.
    function storeRoot(
        string calldata city,
        string calldata period,
        bytes32 root,
        uint32 count
    ) external onlyOwner {
        bytes32 key = _key(city, period);
        require(entries[key].timestamp == 0, "already stored");
        entries[key] = Entry(root, count, uint64(block.timestamp));
        emit RootStored(city, period, root, count, uint64(block.timestamp));
    }

    /// @notice Zincirdeki kökü okur.
    function getRoot(string calldata city, string calldata period)
        external
        view
        returns (bytes32 root, uint32 count, uint64 timestamp)
    {
        Entry memory e = entries[_key(city, period)];
        require(e.timestamp != 0, "not found");
        return (e.root, e.count, e.timestamp);
    }

    /// @notice Bir kaydın (leaf) kanıtla birlikte o ayın köküne ait olduğunu doğrular.
    function verify(
        string calldata city,
        string calldata period,
        bytes32 leaf,
        bytes32[] calldata proof
    ) external view returns (bool) {
        Entry memory e = entries[_key(city, period)];
        require(e.timestamp != 0, "not found");
        bytes32 h = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            bytes32 p = proof[i];
            h = h <= p
                ? keccak256(abi.encodePacked(h, p))
                : keccak256(abi.encodePacked(p, h));
        }
        return h == e.root;
    }
}
