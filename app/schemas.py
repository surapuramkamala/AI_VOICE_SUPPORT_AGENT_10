
from pydantic import BaseModel, ConfigDict, Field


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    status: str


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_number: str
    amount_rupees: int
    status: str
    refund_eligible: bool


class RefundRequestCreate(BaseModel):
    order_number: str = Field(min_length=1, max_length=30)
    amount_rupees: int = Field(gt=0, le=1000000)
    reason: str = Field(min_length=3, max_length=500)


class RefundResponse(BaseModel):
    id: int
    order_number: str
    amount_rupees: int
    status: str
    message: str
    
class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(min_length=1, max_length=100)
#------------------------------

# from pydantic import BaseModel, ConfigDict, Field


# class CustomerResponse(BaseModel):
#     id: int
#     name: str
#     email: str
#     status: str

#     model_config = ConfigDict(from_attributes=True)


# class OrderResponse(BaseModel):
#     id: int
#     order_number: str
#     amount_rupees: int
#     status: str
#     refund_eligible: bool

#     model_config = ConfigDict(from_attributes=True)


# class RefundRequestCreate(BaseModel):
#     order_number: str = Field(
#         ...,
#         min_length=1,
#         max_length=50,
#     )
#     amount_rupees: int = Field(..., gt=0)
#     reason: str = Field(
#         ...,
#         min_length=1,
#         max_length=1000,
#     )


# class RefundResponse(BaseModel):
#     id: int
#     order_id: int
#     amount_rupees: int
#     reason: str
#     status: str

#     model_config = ConfigDict(from_attributes=True)


# class AgentChatRequest(BaseModel):
#     model_config = ConfigDict(extra="forbid")

#     message: str = Field(
#         ...,
#         min_length=1,
#         max_length=4000,
#     )
#     session_id: str = Field(
#         ...,
#         min_length=1,
#         max_length=100,
#     )

