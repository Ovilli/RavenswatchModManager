// invite_friend_click
// caller site (link va): 0x14055d95c
// containing function: FUN_14055d850 @ 0x14055d850


undefined8 *
FUN_14055d850(longlong param_1,undefined8 *param_2,undefined8 param_3,undefined8 param_4)

{
  undefined8 *puVar1;
  char *local_20;
  uint local_18;
  int local_14;
  
  if (*(int *)(param_1 + 0xe0) == -1) {
    if (*(char *)(param_1 + 0x120) == '\0') {
      puVar1 = (undefined8 *)FUN_140205590(&local_20,"$ {} $");
      *param_2 = *puVar1;
      *(uint *)(param_2 + 1) =
           *(uint *)(param_2 + 1) ^ (*(uint *)(param_2 + 1) ^ *(uint *)(puVar1 + 1)) & 0x7fffffff;
      *(uint *)(param_2 + 1) =
           (*(uint *)(param_2 + 1) ^ *(uint *)(puVar1 + 1)) & 0x7fffffff ^ *(uint *)(puVar1 + 1);
      *(undefined4 *)((longlong)param_2 + 0xc) = *(undefined4 *)((longlong)puVar1 + 0xc);
      *puVar1 = &DAT_140eb46d0;
      *(undefined4 *)(puVar1 + 1) = 0x80000000;
      *(undefined4 *)((longlong)puVar1 + 0xc) = 0;
      if (((local_14 != 0) && ((local_18 & 0x80000000) == 0)) && (local_20 != (char *)0x0)) {
        LOCK();
        DAT_14143ea74 = DAT_14143ea74 + 1;
        UNLOCK();
        thunk_FUN_140cbe5f0();
        return param_2;
      }
    }
    else {
      FUN_1401145b0(param_2,param_1 + 0x110);
    }
  }
  else {
    if (*(longlong *)(param_1 + 0xd0) == 0) {
      local_20 = "<local sentence text not loaded>";
      local_18 = 0x80000020;
    }
    else {
      FUN_140671890(*(longlong *)(param_1 + 0xd0),&local_20,*(int *)(param_1 + 0xe0),param_4,0);
    }
    FUN_1401145b0(param_2,&local_20);
  }
  return param_2;
}

