// friend_list_model_call_site
// caller site (link va): 0x140243468
// containing function: FUN_140243440 @ 0x140243440


longlong FUN_140243440(longlong param_1,longlong param_2)

{
  longlong lVar1;
  
  FUN_1401145b0();
  FUN_1401145b0(param_1 + 0x10,param_2 + 0x10);
  *(undefined8 *)(param_1 + 0x20) = *(undefined8 *)(param_2 + 0x20);
  *(undefined1 *)(param_1 + 0x28) = *(undefined1 *)(param_2 + 0x28);
  lVar1 = *(longlong *)(param_2 + 0x30);
  *(longlong *)(param_1 + 0x30) = lVar1;
  if (lVar1 != 0) {
    LOCK();
    *(longlong *)(lVar1 + 8) = *(longlong *)(lVar1 + 8) + 1;
    UNLOCK();
  }
  return param_1;
}

