// caller of text_localizer
// target: 0x14055d850
// caller fn: FUN_14055e5a0 @ 0x14055e5a0


float FUN_14055e5a0(longlong param_1)

{
  longlong lVar1;
  float fVar2;
  undefined1 local_res10 [8];
  float local_res18;
  float local_res1c;
  longlong local_28;
  uint local_20;
  int local_1c;
  
  lVar1 = FUN_140559f10();
  if (lVar1 == 0) {
    lVar1 = param_1 + 0x128;
  }
  lVar1 = *(longlong *)(lVar1 + 0x48);
  if (lVar1 == 0) {
    lVar1 = *(longlong *)(DAT_14140dde8 + 0x50);
  }
  FUN_14055d850(param_1,&local_28);
  fVar2 = DAT_140fa3d60;
  FUN_140641e00(&local_res18,lVar1,local_28,DAT_140fa3d60,0xffffffff,local_res10,0);
  if ((int)(longlong)local_res1c != 0) {
    fVar2 = (float)((longlong)local_res18 & 0xffffffff) /
            (float)((longlong)local_res1c & 0xffffffff);
  }
  if (((local_1c != 0) && ((local_20 & 0x80000000) == 0)) && (local_28 != 0)) {
    LOCK();
    DAT_14143ea74 = DAT_14143ea74 + 1;
    UNLOCK();
    thunk_FUN_140cbe5f0();
  }
  return fVar2;
}

