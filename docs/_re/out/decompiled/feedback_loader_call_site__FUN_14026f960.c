// feedback_loader_call_site
// caller site (link va): 0x14026f99c
// containing function: FUN_14026f960 @ 0x14026f960


longlong FUN_14026f960(longlong param_1,longlong param_2)

{
  longlong lVar1;
  
  lVar1 = FUN_1401c5310(param_1,*(undefined4 *)(param_1 + 8),1);
  FUN_1401145b0(lVar1,param_2);
  FUN_1401145b0(lVar1 + 0x10,param_2 + 0x10);
  *(undefined8 *)(lVar1 + 0x20) = *(undefined8 *)(param_2 + 0x20);
  *(undefined1 *)(lVar1 + 0x28) = *(undefined1 *)(param_2 + 0x28);
  return lVar1;
}

