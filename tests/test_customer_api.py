import pytest


def create_customer(client):
    response = client.post(
        "/customers",
        json={"display_name": "同名合成客户"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_same_name_customers_and_multiple_conversations(client):
    first_id = create_customer(client)
    second_id = create_customer(client)

    assert first_id != second_id

    customer = client.get(f"/customers/{first_id}")
    assert customer.status_code == 200
    assert customer.json()["display_name"] == "同名合成客户"

    conversation_ids = []

    for _ in range(2):
        response = client.post(
            "/conversations",
            json={"customer_id": first_id},
        )
        assert response.status_code == 201

        data = response.json()
        assert data["customer_id"] == first_id
        assert data["customer_name"] == "同名合成客户"

        conversation_ids.append(data["id"])

        fetched = client.get(f"/conversations/{data['id']}")
        assert fetched.json()["customer_id"] == first_id

    assert conversation_ids[0] != conversation_ids[1]


def test_unknown_customer_does_not_create_conversation(client):
    before = client.get("/conversations").json()

    response = client.post(
        "/conversations",
        json={"customer_id": "unknown-customer"},
    )

    assert response.status_code == 404
    assert client.get("/conversations").json() == before
    assert client.get("/customers/unknown-customer").status_code == 404


def test_name_alone_does_not_automatically_bind_customer(client):
    create_customer(client)

    response = client.post(
        "/conversations",
        json={"customer_name": "同名合成客户"},
    )

    assert response.status_code == 201
    assert response.json()["customer_id"] is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"customer_name": "   "},
        {
            "customer_name": "合成客户",
            "customer_id": "some-customer",
        },
    ],
)
def test_conversation_requires_one_customer_reference(client, body):
    response = client.post("/conversations", json=body)

    assert response.status_code == 422
    assert client.get("/conversations").json() == []