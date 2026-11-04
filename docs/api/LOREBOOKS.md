# 世界书 API

[API 总表](../../API_TABLE.md) · [接口维护与校验](README.md)

快速定位：[导入](#post-lorebooksimport) · [读取](#get-lorebookslorebook_id) · [编辑](#put-lorebookslorebook_id) · [绑定角色](#post-lorebookscharacterscharacter_idbindlorebook_id)

## POST `/lorebooks/import`
* **Request**: `multipart/form-data`
  - `file`: JSON file in SillyTavern lorebook format.
* **Response (200 OK)**:
  ```json
  {
    "message": "Lorebook imported successfully",
    "lorebook_id": 1,
    "name": "魔法学院设定集",
    "entries_count": 28
  }
  ```

## GET `/lorebooks`
* **Response (200 OK)**:
  ```json
  {
    "lorebooks": [
      {
        "id": 1,
        "name": "魔法学院设定集",
        "description": "学院的历史、老师与禁忌设定集",
        "scan_depth": 5,
        "token_budget": 3000,
        "recursive_scanning": true,
        "entries_count": 28,
        "created_at": "2026-05-23T16:00:19"
      }
    ]
  }
  ```

## GET `/lorebooks/{lorebook_id}`
* **Response (200 OK)**:
  ```json
  {
    "id": 1,
    "name": "魔法学院设定集",
    "description": "学院的历史...",
    "scan_depth": 5,
    "token_budget": 3000,
    "recursive_scanning": true,
    "entries": [
      {
        "keys": ["学院", "魔法学院"],
        "content": "魔法学院创立于西历120年，是一座历史悠久的建筑...",
        "enabled": true,
        "constant": false,
        "case_sensitive": false,
        "selective": false,
        "secondary_keys": [],
        "position": "before_char",
        "insertion_order": 100
      }
    ],
    "created_at": "2026-05-23T16:00:19"
  }
  ```

## PUT `/lorebooks/{lorebook_id}`
* **Request (JSON)**: *(All fields optional)*
<!-- request-example: PUT /lorebooks/{lorebook_id} -->
  ```json
  {
    "name": "更新设定集名称",
    "description": "更新后的描述",
    "scan_depth": 8,
    "token_budget": 4000,
    "recursive_scanning": false,
    "entries": [
      {
        "keys": ["魔法师"],
        "content": "本世界的魔法师等级分为初级、中级、高级...",
        "enabled": true,
        "constant": false,
        "case_sensitive": false,
        "selective": false,
        "secondary_keys": [],
        "position": "before_char",
        "insertion_order": 100
      }
    ]
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "message": "Lorebook updated successfully",
    "lorebook_id": 1,
    "name": "更新设定集名称",
    "entries_count": 1
  }
  ```

## DELETE `/lorebooks/{lorebook_id}` (or POST `/lorebooks/{lorebook_id}/delete`)
* **Response (200 OK)**:
  ```json
  {
    "message": "Lorebook deleted successfully",
    "lorebook_id": 1
  }
  ```

## POST `/lorebooks/characters/{character_id}/bind/{lorebook_id}`
* **Response (200 OK)**:
  ```json
  {
    "message": "Successfully bound lorebook '魔法学院设定集' to character '爱丽丝'",
    "character_id": 1,
    "lorebook_id": 1
  }
  ```

## POST `/lorebooks/characters/{character_id}/unbind/{lorebook_id}`
* **Response (200 OK)**:
  ```json
  {
    "message": "Successfully unbound lorebook '魔法学院设定集' from character '爱丽丝'",
    "character_id": 1,
    "lorebook_id": 1
  }
  ```

---
