// caller of text_localizer
// target: 0x14055d850
// caller fn: FUN_14055e690 @ 0x14055e690


void FUN_14055e690(longlong param_1,longlong param_2,undefined8 param_3,undefined8 param_4)

{
  longlong lVar1;
  undefined8 uVar2;
  bool bVar3;
  uint uVar4;
  longlong local_70;
  uint local_68;
  int local_64;
  char *local_60;
  uint local_58;
  int local_50;
  longlong local_48;
  int local_40;
  int local_3c;
  undefined4 local_38;
  char *local_30;
  uint local_28;
  int local_24;
  
  local_50 = *(int *)(param_1 + 0x40);
  FUN_1401145b0(&local_48,param_1 + 0x48,param_3,param_4,0);
  bVar3 = local_50 == 0;
  uVar4 = 0;
  if (((local_3c != 0) && (-1 < local_40)) && (local_48 != 0)) {
    LOCK();
    DAT_14143ea74 = DAT_14143ea74 + 1;
    UNLOCK();
    thunk_FUN_140cbe5f0(local_48);
  }
  if (bVar3) {
    if (*(int *)(param_1 + 0xe0) == -1) {
      FUN_140114760(param_2,param_1 + 0x110);
    }
    else {
      FUN_140670c70(param_1 + 0xa0,param_2,param_3,param_4,uVar4);
    }
  }
  else {
    local_38 = *(undefined4 *)(param_1 + 0x40);
    FUN_1401145b0(&local_30,param_1 + 0x48);
    local_60 = "";
    if (*local_30 != '\0') {
      local_60 = local_30;
    }
    lVar1 = -1;
    do {
      lVar1 = lVar1 + 1;
    } while (local_30[lVar1] != '\0');
    local_58 = ((uint)lVar1 ^ local_28) & 0x7fffffff ^ local_28;
    FUN_140511120(param_2,&local_60,param_3,param_4,uVar4 | 2);
    uVar4 = uVar4 & 0xfffffffd;
    if ((local_24 != 0) && (-1 < (int)local_28)) {
      LOCK();
      DAT_14143ea74 = DAT_14143ea74 + 1;
      UNLOCK();
      thunk_FUN_140cbe5f0(local_30);
    }
  }
  if ((*(uint *)(param_2 + 8) & 0x7fffffff) == 0) {
    uVar2 = FUN_14055d850(param_1,&local_70,param_3,param_4,uVar4);
    FUN_140202ed0(param_2,uVar2);
    if (((local_64 != 0) && ((local_68 & 0x80000000) == 0)) && (local_70 != 0)) {
      LOCK();
      DAT_14143ea74 = DAT_14143ea74 + 1;
      UNLOCK();
      thunk_FUN_140cbe5f0();
    }
  }
  return;
}

